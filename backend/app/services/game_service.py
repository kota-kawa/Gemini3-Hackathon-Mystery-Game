from __future__ import annotations

import uuid

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
    GameStateResponse,
    GuessRequest,
    MessageResponse,
    NewGameResponse,
    PatchLanguageResponse,
    UnlockedEvidenceResponse,
)
from .llm_client import LLMClient, LLMError
from .scoring_service import ScoringService


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

        return NewGameResponse(
            game_id=game.id,
            case_summary=self._case_summary(case_obj),
            characters=self._public_characters(case_obj),
            initial_state=GameStatus(game.status),
            remaining_questions=game.remaining_questions,
            language_mode=LanguageMode(game.language_mode),
        )

    def ask(self, game_id: str, request: AskRequest):
        game = self._get_game_or_404(game_id)
        if GameStatus(game.status) != GameStatus.PLAYING:
            raise conflict(
                "質問できるのはPLAYING状態のみです。",
                detail={"status": game.status},
            )

        case_obj = self._case_of_game(game)

        history = [
            {"question": message.question, "answer": message.answer_text, "target": message.target}
            for message in game.messages
        ]

        try:
            answer = self.llm_client.answer_question(
                case_data=case_obj,
                question=request.question,
                target=request.target,
                history=history,
                language_mode=LanguageMode(game.language_mode),
            )
            contradiction = self.llm_client.contradiction_check(
                case_data=case_obj,
                question=request.question,
                answer=answer,
                language_mode=LanguageMode(game.language_mode),
            )
        except LLMError as exc:
            raise gemini_error(
                "通信に失敗しました。再試行してください。",
                detail={"cause": str(exc)},
            ) from exc

        if not isinstance(contradiction, dict):
            contradiction = {}

        fixed_answer = contradiction.get("fixed_answer")
        if contradiction.get("contradiction") and fixed_answer:
            answer = str(fixed_answer)

        game.remaining_questions = max(0, game.remaining_questions - 1)
        if game.remaining_questions == 0:
            game.status = GameStatus.GUESSING.value

        unlocked = self._unlock_next_evidence(game=game, case_obj=case_obj)

        message = Message(
            game_id=game.id,
            question=request.question,
            target=request.target,
            answer_text=answer,
            language_mode=game.language_mode,
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(game)

        return {
            "answer_text": answer,
            "remaining_questions": game.remaining_questions,
            "status": GameStatus(game.status),
            "unlocked_evidence": unlocked,
        }

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

        messages = [MessageResponse.model_validate(msg) for msg in sorted(game.messages, key=lambda m: m.created_at)]

        return GameStateResponse(
            game_id=game.id,
            status=GameStatus(game.status),
            remaining_questions=game.remaining_questions,
            language_mode=LanguageMode(game.language_mode),
            case_summary=self._case_summary(case_obj),
            characters=self._public_characters(case_obj),
            unlocked_evidence=unlocked,
            messages=messages,
        )

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

    def _generate_validated_case(self, language_mode: LanguageMode) -> CaseFile:
        errors: list[str] = []
        for _ in range(2):
            try:
                payload = self.llm_client.generate_case(language_mode)
                return CaseFile.model_validate(payload)
            except (LLMError, ValueError, ValidationError) as exc:
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
