from __future__ import annotations

import re
from difflib import SequenceMatcher

from ..enums import LanguageMode
from ..schemas import CaseFile, GuessRequest


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.strip().lower())


def _tokenize(text: str) -> set[str]:
    return {token for token in re.split(r"[^\w\u3040-\u30ff\u3400-\u9fff]+", text.lower()) if token}


def _semantic_score(answer: str, truth: str, max_points: int = 20) -> tuple[int, bool]:
    a = _normalize(answer)
    t = _normalize(truth)
    if not a or not t:
        return 0, False

    ratio = SequenceMatcher(None, a, t).ratio()
    ta = _tokenize(answer)
    tt = _tokenize(truth)
    overlap = len(ta & tt) / max(1, len(tt))
    blended = max(ratio, overlap)
    points = int(round(max_points * blended))
    return min(max_points, points), points >= int(max_points * 0.6)


def _grade(score: int) -> str:
    if score >= 90:
        return "S"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    return "C"


class ScoringService:
    def evaluate(
        self,
        *,
        case_data: CaseFile,
        guess: GuessRequest,
        language_mode: LanguageMode,
        llm_result: dict | None = None,
    ) -> dict:
        if llm_result and self._llm_payload_looks_valid(llm_result):
            return llm_result

        killer = next(c for c in case_data.characters if c.id == case_data.killer_id)
        killer_match = _normalize(guess.killer) in {
            _normalize(killer.name),
            _normalize(killer.id),
        }

        motive_points, motive_match = _semantic_score(guess.motive, case_data.motive)
        method_points, method_match = _semantic_score(guess.method, case_data.method)
        trick_points, trick_match = _semantic_score(guess.trick, case_data.trick)

        score = (40 if killer_match else 0) + motive_points + method_points + trick_points
        grade = _grade(score)

        contradictions: list[str] = []
        if "10:12" in guess.reasoning:
            contradictions.append(
                "10:12の目撃証言を事実として採用しており、証拠時系列と衝突しています。"
                if language_mode == LanguageMode.JA
                else "You relied on the 10:12 witness claim, which conflicts with evidence timeline."
            )
        if "停電" not in guess.reasoning and "blackout" not in guess.reasoning.lower():
            contradictions.append(
                "停電タイミングの検証が不足しています。"
                if language_mode == LanguageMode.JA
                else "Your reasoning does not verify the blackout timing."
            )

        weaknesses = self._weaknesses(
            language_mode=language_mode,
            killer_match=killer_match,
            motive_match=motive_match,
            method_match=method_match,
            trick_match=trick_match,
        )

        if language_mode == LanguageMode.EN:
            feedback = (
                f"Killer {'correct' if killer_match else 'incorrect'}. "
                f"Motive/method/trick alignment: {motive_points}/20, {method_points}/20, {trick_points}/20."
            )
            solution_summary = (
                f"{case_data.truth.solution} The room appeared locked because {case_data.truth.why_room_was_locked} "
                f"The alibi deception worked because {case_data.truth.how_alibi_was_faked}"
            )
        else:
            feedback = (
                f"犯人推定は{'正解' if killer_match else '不正解'}。"
                f"動機/手口/トリックの一致度は {motive_points}/20, {method_points}/20, {trick_points}/20 です。"
            )
            solution_summary = (
                f"{case_data.truth.solution} 密室化は {case_data.truth.why_room_was_locked}。"
                f"アリバイ偽装は {case_data.truth.how_alibi_was_faked}"
            )

        return {
            "score": score,
            "grade": grade,
            "matches": {
                "killer": killer_match,
                "motive": motive_match,
                "method": method_match,
                "trick": trick_match,
            },
            "feedback": feedback,
            "contradictions": contradictions,
            "weaknesses_top3": weaknesses,
            "solution_summary": solution_summary,
        }

    def _weaknesses(
        self,
        *,
        language_mode: LanguageMode,
        killer_match: bool,
        motive_match: bool,
        method_match: bool,
        trick_match: bool,
    ) -> list[str]:
        if language_mode == LanguageMode.EN:
            items = [
                "You did not connect each claim to a concrete evidence item.",
                "Timeline interpretation around the blackout needs tighter validation.",
                "The liar NPC testimony was not sufficiently cross-checked.",
            ]
            if not killer_match:
                items[0] = "Suspect elimination logic was weak, leading to wrong killer selection."
            if not motive_match:
                items[1] = "Motive analysis missed the financial-pressure thread."
            if not method_match or not trick_match:
                items[2] = "Mechanism of delayed latch reset and gas setup was underexplained."
            return items[:3]

        items = [
            "主張ごとに対応する証拠を明示できていません。",
            "停電前後の時系列解釈が甘く、検証が不足しています。",
            "嘘つきNPCの証言を裏取りせずに採用しています。",
        ]
        if not killer_match:
            items[0] = "容疑者の消去法が弱く、犯人特定を誤っています。"
        if not motive_match:
            items[1] = "金銭圧力の動機線を十分に拾えていません。"
        if not method_match or not trick_match:
            items[2] = "遅延噴射とラッチ復帰の仕組み説明が不足しています。"
        return items[:3]

    def _llm_payload_looks_valid(self, payload: dict) -> bool:
        required = {"score", "grade", "matches", "feedback", "contradictions", "weaknesses_top3", "solution_summary"}
        if not required.issubset(payload.keys()):
            return False
        if not isinstance(payload.get("matches"), dict):
            return False
        return True
