from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..config import Settings
from ..enums import GameStatus, LanguageMode
from ..errors import AppError, conflict, gemini_error, not_found
from ..models import Case, Game, Guess, Message
from ..schemas import (
    AskRequest,
    CaseFile,
    CharacterPublicResponse,
    CaseSummaryResponse,
    ConversationSummaryResponse,
    GameStateResponse,
    GuessRequest,
    MessageResponse,
    NewGameResponse,
    PatchLanguageResponse,
    UnlockedEvidenceResponse,
)
from .follow_up import append_follow_up_block, heuristic_follow_up_questions, split_answer_and_follow_up_questions
from .llm_client import GeneratedImage, LLMClient, LLMError
from .scoring_service import ScoringService

logger = logging.getLogger(__name__)
MEDIA_TYPE_TO_EXTENSION = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


class GameService:
    def __init__(
        self,
        *,
        db: Session,
        llm_client: LLMClient,
        scoring_service: ScoringService,
        settings: Settings,
    ) -> None:
        self.db = db
        self.llm_client = llm_client
        self.scoring_service = scoring_service
        self.settings = settings

    def create_game(self, language_mode: LanguageMode) -> NewGameResponse:
        case_obj = self._generate_validated_case(language_mode)

        game = Game(
            id=str(uuid.uuid4()),
            status=GameStatus.PLAYING.value,
            remaining_questions=self.settings.max_questions,
            language_mode=language_mode.value,
            unlocked_evidence_count=0,
        )
        case = Case(
            game_id=game.id,
            case_id=case_obj.case_id,
            title=case_obj.title,
            payload=case_obj.model_dump(),
        )
        game.case = case

        self.db.add(game)
        self.db.commit()
        self.db.refresh(game)
        background_image_url = self._generate_story_background(
            game_id=game.id,
            case_obj=case_obj,
            language_mode=language_mode,
        )

        return NewGameResponse(
            game_id=game.id,
            case_summary=self._case_summary(case_obj),
            characters=self._public_characters(case_obj),
            initial_state=GameStatus(game.status),
            remaining_questions=game.remaining_questions,
            language_mode=LanguageMode(game.language_mode),
            background_image_url=background_image_url,
        )

    def ask(self, game_id: str, request: AskRequest):
        game = self._get_game_or_404(game_id)
        if GameStatus(game.status) != GameStatus.PLAYING:
            raise conflict(
                "質問できるのはPLAYING状態のみです。",
                detail={"status": game.status},
            )

        case_obj = self._case_of_game(game)
        language_mode = LanguageMode(game.language_mode)

        history = self._history_of_game(game)

        try:
            raw_answer = self.llm_client.answer_question(
                case_data=case_obj,
                question=request.question,
                history=history,
                language_mode=language_mode,
            )
        except LLMError as exc:
            raise gemini_error(
                "通信に失敗しました。再試行してください。",
                detail={"cause": str(exc)},
            ) from exc

        answer, follow_up_questions = split_answer_and_follow_up_questions(
            raw_answer,
            language_mode=language_mode,
            with_default=False,
        )
        if not follow_up_questions:
            follow_up_questions = heuristic_follow_up_questions(
                case_data=case_obj,
                language_mode=language_mode,
                history_count=len(history),
            )

        try:
            contradiction = self.llm_client.contradiction_check(
                case_data=case_obj,
                question=request.question,
                answer=answer,
                language_mode=language_mode,
            )
        except LLMError as exc:
            logger.warning("Contradiction check failed; using original answer without rewrite: %s", exc)
            contradiction = {"contradiction": False, "fixed_answer": answer}

        if not isinstance(contradiction, dict):
            contradiction = {}

        fixed_answer = contradiction.get("fixed_answer")
        if contradiction.get("contradiction") and fixed_answer:
            rewritten_answer, rewritten_followups = split_answer_and_follow_up_questions(
                str(fixed_answer),
                language_mode=language_mode,
                with_default=False,
            )
            answer = rewritten_answer
            if rewritten_followups:
                follow_up_questions = rewritten_followups
            elif not follow_up_questions:
                follow_up_questions = heuristic_follow_up_questions(
                    case_data=case_obj,
                    language_mode=language_mode,
                    history_count=len(history),
                )

        if not self._answer_has_named_actor(answer=answer, case_obj=case_obj):
            answer = self._build_explicit_actor_answer(
                case_obj=case_obj,
                question=request.question,
                language_mode=language_mode,
            )

        game.remaining_questions = max(0, game.remaining_questions - 1)
        if game.remaining_questions == 0:
            game.status = GameStatus.GUESSING.value

        unlocked = self._unlock_next_evidence(game=game, case_obj=case_obj)

        message = Message(
            game_id=game.id,
            question=request.question,
            answer_text=append_follow_up_block(
                answer,
                follow_up_questions,
                language_mode=language_mode,
            ),
            language_mode=game.language_mode,
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(game)

        return {
            "answer_text": answer,
            "follow_up_questions": follow_up_questions,
            "remaining_questions": game.remaining_questions,
            "status": GameStatus(game.status),
            "unlocked_evidence": unlocked,
        }

    def summarize_conversation(self, game_id: str) -> ConversationSummaryResponse:
        game = self._get_game_or_404(game_id)
        if GameStatus(game.status) == GameStatus.ENDED:
            raise conflict(
                "ENDED状態のゲームは要約できません。",
                detail={"status": game.status},
            )

        language_mode = LanguageMode(game.language_mode)
        case_obj = self._case_of_game(game)
        history = self._history_of_game(game)

        unknown = "unknown from conversation" if language_mode == LanguageMode.EN else "会話からは不明"
        if not history:
            no_messages = "No chat messages yet." if language_mode == LanguageMode.EN else "まだ会話ログがありません。"
            return ConversationSummaryResponse(
                killer=unknown,
                method=unknown,
                motive=unknown,
                trick=unknown,
                highlights=[no_messages],
            )

        try:
            raw = self.llm_client.summarize_conversation(
                case_data=case_obj,
                history=history,
                language_mode=language_mode,
            )
        except LLMError as exc:
            raise gemini_error(
                "会話要約の生成に失敗しました。再試行してください。",
                detail={"cause": str(exc)},
            ) from exc

        if not isinstance(raw, dict):
            raw = {}

        highlights_raw = raw.get("highlights")
        highlights: list[str] = []
        if isinstance(highlights_raw, list):
            for item in highlights_raw:
                if not isinstance(item, str):
                    continue
                cleaned = item.strip()
                if cleaned and cleaned not in highlights:
                    highlights.append(cleaned)
                if len(highlights) >= 3:
                    break

        return ConversationSummaryResponse(
            killer=self._normalize_summary_value(raw.get("killer"), unknown),
            method=self._normalize_summary_value(raw.get("method"), unknown),
            motive=self._normalize_summary_value(raw.get("motive"), unknown),
            trick=self._normalize_summary_value(raw.get("trick"), unknown),
            highlights=highlights,
        )

    def submit_guess(self, game_id: str, request: GuessRequest):
        game = self._get_game_or_404(game_id)
        if GameStatus(game.status) != GameStatus.GUESSING:
            raise conflict(
                "推理提出はGUESSING状態のみ可能です。",
                detail={"status": game.status},
            )

        case_obj = self._case_of_game(game)

        llm_result = None
        try:
            llm_result = self.llm_client.score_guess(
                case_data=case_obj,
                guess=request,
                language_mode=LanguageMode(game.language_mode),
            )
        except LLMError:
            llm_result = None

        scored = self.scoring_service.evaluate(
            case_data=case_obj,
            guess=request,
            language_mode=LanguageMode(game.language_mode),
            llm_result=llm_result,
        )

        guess_row = game.guess
        if guess_row is None:
            guess_row = Guess(game_id=game.id)
            self.db.add(guess_row)

        guess_row.killer = request.killer
        guess_row.motive = request.motive
        guess_row.method = request.method
        guess_row.trick = request.trick
        guess_row.reasoning = request.reasoning
        guess_row.score = int(scored["score"])
        guess_row.grade = scored["grade"]
        guess_row.feedback = {
            "text": scored["feedback"],
            "matches": scored["matches"],
            "contradictions": scored["contradictions"],
        }
        guess_row.weaknesses_top3 = scored["weaknesses_top3"]
        guess_row.solution_summary = scored["solution_summary"]

        game.status = GameStatus.RESULT.value

        self.db.commit()

        return {
            "score": int(scored["score"]),
            "grade": scored["grade"],
            "matches": scored["matches"],
            "feedback": scored["feedback"],
            "contradictions": scored["contradictions"],
            "weaknesses_top3": scored["weaknesses_top3"],
            "solution_summary": scored["solution_summary"],
        }

    def patch_language(self, game_id: str, language_mode: LanguageMode) -> PatchLanguageResponse:
        game = self._get_game_or_404(game_id)
        if GameStatus(game.status) == GameStatus.ENDED:
            raise conflict("ENDED状態のゲームは更新できません。", detail={"status": game.status})

        game.language_mode = language_mode.value
        self.db.commit()
        return PatchLanguageResponse(game_id=game.id, language_mode=language_mode)

    def get_game(self, game_id: str) -> GameStateResponse:
        game = self._get_game_or_404(game_id)
        case_obj = self._case_of_game(game)

        unlocked = [
            UnlockedEvidenceResponse(**item.model_dump())
            for item in case_obj.evidence[: game.unlocked_evidence_count]
        ]

        messages: list[MessageResponse] = []
        for message in sorted(game.messages, key=lambda m: m.created_at):
            clean_answer, follow_up_questions = split_answer_and_follow_up_questions(
                message.answer_text,
                language_mode=LanguageMode(message.language_mode),
                with_default=False,
            )
            messages.append(
                MessageResponse(
                    id=message.id,
                    question=message.question,
                    answer_text=clean_answer,
                    follow_up_questions=follow_up_questions,
                    language_mode=LanguageMode(message.language_mode),
                    created_at=message.created_at,
                )
            )

        return GameStateResponse(
            game_id=game.id,
            status=GameStatus(game.status),
            remaining_questions=game.remaining_questions,
            language_mode=LanguageMode(game.language_mode),
            background_image_url=self._background_image_url(game.id),
            case_summary=self._case_summary(case_obj),
            characters=self._public_characters(case_obj),
            unlocked_evidence=unlocked,
            messages=messages,
        )

    def get_background_asset(self, game_id: str) -> tuple[Path, str]:
        _ = self._get_game_or_404(game_id)
        meta = self._load_background_meta(game_id)
        if not meta:
            raise not_found("背景画像が見つかりません。", detail={"game_id": game_id})

        file_name = meta.get("file_name")
        media_type = meta.get("media_type")
        if not isinstance(file_name, str) or not file_name:
            raise not_found("背景画像が見つかりません。", detail={"game_id": game_id})
        if not isinstance(media_type, str) or not media_type:
            media_type = "image/png"

        image_path = self._background_dir() / file_name
        if not image_path.is_file():
            raise not_found("背景画像が見つかりません。", detail={"game_id": game_id})
        return image_path, media_type

    def move_to_guessing(self, game_id: str) -> None:
        game = self._get_game_or_404(game_id)
        if GameStatus(game.status) != GameStatus.PLAYING:
            raise conflict("PLAYING状態のゲームのみ遷移可能です。", detail={"status": game.status})
        game.status = GameStatus.GUESSING.value
        self.db.commit()

    def end_game(self, game_id: str) -> None:
        game = self._get_game_or_404(game_id)
        game.status = GameStatus.ENDED.value
        self.db.commit()

    def _background_dir(self) -> Path:
        path = Path(self.settings.generated_background_dir).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path

    def _background_meta_path(self, game_id: str) -> Path:
        return self._background_dir() / f"{game_id}.json"

    def _load_background_meta(self, game_id: str) -> dict[str, str] | None:
        meta_path = self._background_meta_path(game_id)
        if not meta_path.is_file():
            return None

        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to read background metadata for game_id=%s", game_id)
            return None

        if not isinstance(data, dict):
            return None
        return {
            "file_name": str(data.get("file_name", "")),
            "media_type": str(data.get("media_type", "")),
        }

    def _background_image_url(self, game_id: str) -> str | None:
        meta = self._load_background_meta(game_id)
        if not meta:
            return None

        file_name = meta.get("file_name", "")
        if not file_name:
            return None

        image_path = self._background_dir() / file_name
        if not image_path.is_file():
            return None
        return f"/api/game/{game_id}/background"

    def _store_background_image(self, game_id: str, generated: GeneratedImage) -> str:
        media_type = generated.mime_type.strip().lower()
        extension = MEDIA_TYPE_TO_EXTENSION.get(media_type, "png")
        directory = self._background_dir()
        directory.mkdir(parents=True, exist_ok=True)

        for existing in directory.glob(f"{game_id}.*"):
            if existing.is_file():
                existing.unlink()

        file_name = f"{game_id}.{extension}"
        image_path = directory / file_name
        image_path.write_bytes(generated.data)

        meta_path = self._background_meta_path(game_id)
        meta = {"file_name": file_name, "media_type": media_type}
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        return f"/api/game/{game_id}/background"

    def _generate_story_background(
        self,
        *,
        game_id: str,
        case_obj: CaseFile,
        language_mode: LanguageMode,
    ) -> str | None:
        try:
            generated = self.llm_client.generate_background_image(
                case_data=case_obj,
                language_mode=language_mode,
            )
        except LLMError as exc:
            logger.warning("Background image generation failed for game_id=%s: %s", game_id, exc)
            return None

        if generated is None:
            return None
        if not generated.data:
            logger.warning("Background image generation returned empty data for game_id=%s", game_id)
            return None

        try:
            return self._store_background_image(game_id, generated)
        except OSError as exc:
            logger.warning("Failed to store background image for game_id=%s: %s", game_id, exc)
            return None

    def _generate_validated_case(self, language_mode: LanguageMode) -> CaseFile:
        errors: list[str] = []
        for _ in range(2):
            try:
                payload = self.llm_client.generate_case(language_mode)
                return CaseFile.model_validate(payload)
            except LLMError as exc:
                # LLM client already handles retry internally; avoid retry storms on provider errors.
                errors.append(str(exc))
                break
            except (ValueError, ValidationError) as exc:
                errors.append(str(exc))

        raise gemini_error(
            "事件生成に失敗しました。再試行してください。",
            detail={"cause": " | ".join(errors)},
        )

    def _get_game_or_404(self, game_id: str) -> Game:
        game = self.db.get(Game, game_id)
        if game is None:
            raise not_found("指定されたゲームが見つかりません。", detail={"game_id": game_id})
        return game

    @staticmethod
    def _normalize_summary_value(value: object, unknown: str) -> str:
        if not isinstance(value, str):
            return unknown
        cleaned = value.strip()
        return cleaned if cleaned else unknown

    @staticmethod
    def _history_of_game(game: Game) -> list[dict[str, str]]:
        history: list[dict[str, str]] = []
        for message in sorted(game.messages, key=lambda m: m.created_at):
            clean_answer, _ = split_answer_and_follow_up_questions(
                message.answer_text,
                language_mode=LanguageMode(message.language_mode),
                with_default=False,
            )
            history.append({"question": message.question, "answer": clean_answer})
        return history

    def _case_of_game(self, game: Game) -> CaseFile:
        if game.case is None:
            raise AppError(
                status_code=500,
                error_code="CASE_MISSING",
                message="ゲームに対応する事件データが存在しません。",
                retryable=False,
                detail={"game_id": game.id},
            )
        return CaseFile.model_validate(game.case.payload)

    def _unlock_next_evidence(self, *, game: Game, case_obj: CaseFile) -> UnlockedEvidenceResponse | None:
        if game.unlocked_evidence_count >= len(case_obj.evidence):
            return None

        evidence = case_obj.evidence[game.unlocked_evidence_count]
        game.unlocked_evidence_count += 1

        return UnlockedEvidenceResponse(
            id=evidence.id,
            name=evidence.name,
            detail=evidence.detail,
            relevance=evidence.relevance,
        )

    @staticmethod
    def _answer_has_named_actor(*, answer: str, case_obj: CaseFile) -> bool:
        return any(character.name in answer for character in case_obj.characters)

    @staticmethod
    def _build_explicit_actor_answer(
        *,
        case_obj: CaseFile,
        question: str,
        language_mode: LanguageMode,
    ) -> str:
        first = case_obj.characters[0]
        second = case_obj.characters[1]
        third = case_obj.characters[2]
        first_event = case_obj.timeline[0]
        first_evidence = case_obj.evidence[0]
        q = question.lower()

        if language_mode == LanguageMode.EN:
            if any(k in q for k in ["where", "alibi", "at the time", "when"]):
                return (
                    f"{first.name} says: {first.alibi} "
                    f"{second.name} says: {second.alibi}"
                )
            if any(k in q for k in ["evidence", "clue", "proof"]):
                return (
                    f"For evidence '{first_evidence.name}', compare {first.name}'s account "
                    f"('{first.alibi}') with {second.name}'s account ('{second.alibi}')."
                )
            return (
                f"At {first_event.time}, {first_event.event} "
                f"{first.name} says: {first.alibi} "
                f"{third.name} says: {third.alibi}"
            )

        if any(k in question for k in ["どこ", "アリバイ", "当時", "いつ"]):
            return (
                f"{first.name}は「{first.alibi}」と証言しています。"
                f"{second.name}は「{second.alibi}」と証言しています。"
            )
        if any(k in question for k in ["証拠", "手掛かり", "手がかり"]):
            return (
                f"証拠「{first_evidence.name}」の確認では、{first.name}の行動「{first.alibi}」と"
                f"{second.name}の行動「{second.alibi}」を照合してください。"
            )
        return (
            f"{first_event.time}の時点では{first_event.event}。"
            f"{first.name}は「{first.alibi}」、{third.name}は「{third.alibi}」と証言しています。"
        )

    @staticmethod
    def _case_summary(case_obj: CaseFile) -> CaseSummaryResponse:
        return CaseSummaryResponse(
            title=case_obj.title,
            location=case_obj.setting.location,
            time_window=case_obj.setting.time_window,
            summary=case_obj.setting.summary,
            victim_name=case_obj.victim.name,
            found_state=case_obj.victim.found_state,
        )

    @staticmethod
    def _public_characters(case_obj: CaseFile) -> list[CharacterPublicResponse]:
        return [
            CharacterPublicResponse(
                id=character.id,
                name=character.name,
                role=character.role,
                traits=character.traits,
            )
            for character in case_obj.characters
        ]
