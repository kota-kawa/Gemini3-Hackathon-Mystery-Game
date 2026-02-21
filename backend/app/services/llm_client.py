from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ..config import Settings
from ..enums import LanguageMode
from ..schemas import CaseFile, GuessRequest
from .local_case_factory import build_local_case
from .prompts import (
    build_answer_prompt,
    build_case_generation_prompt,
    build_contradiction_prompt,
    build_scoring_prompt,
)


class LLMError(RuntimeError):
    pass


class LLMClient:
    def generate_case(self, language_mode: LanguageMode) -> dict:
        raise NotImplementedError

    def answer_question(
        self,
        *,
        case_data: CaseFile,
        question: str,
        target: str | None,
        history: list[dict],
        language_mode: LanguageMode,
    ) -> str:
        raise NotImplementedError

    def contradiction_check(
        self,
        *,
        case_data: CaseFile,
        question: str,
        answer: str,
        language_mode: LanguageMode,
    ) -> dict:
        raise NotImplementedError

    def score_guess(
        self,
        *,
        case_data: CaseFile,
        guess: GuessRequest,
        language_mode: LanguageMode,
    ) -> dict | None:
        raise NotImplementedError


class FakeLLMClient(LLMClient):
    def generate_case(self, language_mode: LanguageMode) -> dict:
        return build_local_case(language_mode)

    def answer_question(
        self,
        *,
        case_data: CaseFile,
        question: str,
        target: str | None,
        history: list[dict],
        language_mode: LanguageMode,
    ) -> str:
        q = question.lower()
        killer = next(c for c in case_data.characters if c.id == case_data.killer_id)
        liar = next(c for c in case_data.characters if c.id == case_data.liar_id)

        if language_mode == LanguageMode.EN:
            unclear = "Could you narrow it down to person, timeline, or evidence?"
            spoiler_block = "I cannot reveal the final answer yet, but I can share clues."
            if any(x in q for x in ["killer", "who did it", "solution"]):
                return spoiler_block
            if any(x in q for x in ["evidence", "proof", "clue"]):
                first = case_data.evidence[min(len(history), len(case_data.evidence) - 1)]
                return f"One clue is '{first.name}'. {first.detail} It matters because {first.relevance}"
            if any(x in q for x in ["timeline", "time", "when"]):
                event = case_data.timeline[min(len(history), len(case_data.timeline) - 1)]
                return f"At {event.time}, {event.event}"
            if target and target.lower() in {liar.id.lower(), liar.name.lower()}:
                lied_before = any(liar.name in row.get("answer", "") and "10:12" in row.get("answer", "") for row in history)
                if not lied_before:
                    return f"{liar.name} says they saw the victim speaking at 10:12 near the corridor."
                return f"{liar.name} now claims they mostly stayed near the elevator hall during the blackout."
            if any(x in q for x in ["motive", "why"]):
                return "The motive likely ties to hidden financial pressure and a silence attempt."
            if any(x in q for x in ["method", "how"]):
                return "The method likely involved delayed gas release rather than direct violence."
            if any(x in q for x in ["alibi"]):
                return f"Check who benefited from the blackout window and compare with {killer.name}'s movements."
            if len(question.strip()) < 3:
                return unclear
            return "Focus on the blackout window, latch behavior, and witness timing conflicts."

        unclear = "人物・時系列・証拠のどれを知りたいか絞ってください。"
        spoiler_block = "真相の断定はまだできませんが、手掛かりは共有できます。"
        if any(x in q for x in ["犯人", "真相", "答え"]):
            return spoiler_block
        if any(x in q for x in ["証拠", "手掛かり", "手がかり"]):
            first = case_data.evidence[min(len(history), len(case_data.evidence) - 1)]
            return f"手掛かりは『{first.name}』です。{first.detail} 重要性は、{first.relevance}"
        if any(x in q for x in ["時系列", "時間", "いつ"]):
            event = case_data.timeline[min(len(history), len(case_data.timeline) - 1)]
            return f"{event.time}の時点で、{event.event}"
        if target and target.lower() in {liar.id.lower(), liar.name.lower()}:
            lied_before = any(liar.name in row.get("answer", "") and "10:12" in row.get("answer", "") for row in history)
            if not lied_before:
                return f"{liar.name}の証言では、被害者は10:12ごろ廊下で話していたそうです。"
            return f"{liar.name}は、停電中はほぼエレベーターホールにいたと言っています。"
        if any(x in q for x in ["動機", "なぜ"]):
            return "動機は金銭面の圧力と、発覚回避の線が濃いです。"
        if any(x in q for x in ["手口", "方法", "どうやって"]):
            return "直接的な暴行より、遅延作動型の仕掛けが疑われます。"
        if any(x in q for x in ["アリバイ"]):
            return f"停電の空白時間で得をする人物と、{killer.name}の移動を照合してください。"
        if len(question.strip()) < 3:
            return unclear
        return "停電のタイミング、ラッチの挙動、証言時刻の食い違いを重点的に見てください。"

    def contradiction_check(
        self,
        *,
        case_data: CaseFile,
        question: str,
        answer: str,
        language_mode: LanguageMode,
    ) -> dict:
        killer = next(c for c in case_data.characters if c.id == case_data.killer_id)
        if killer.name in answer and ("犯人" in answer or "killer" in answer.lower()):
            replacement = (
                "犯人を断定する段階ではありません。証拠と時系列を照合しましょう。"
                if language_mode == LanguageMode.JA
                else "It is too early to identify the killer directly. Compare evidence and timeline first."
            )
            return {
                "contradiction": True,
                "reason": "direct spoiler",
                "fixed_answer": replacement,
            }

        return {
            "contradiction": False,
            "reason": "none",
            "fixed_answer": answer,
        }

    def score_guess(
        self,
        *,
        case_data: CaseFile,
        guess: GuessRequest,
        language_mode: LanguageMode,
    ) -> dict | None:
        return None


@dataclass
class GeminiLLMClient(LLMClient):
    settings: Settings

    def _extract_json(self, raw_text: str) -> dict:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned)
            cleaned = cleaned.replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if not match:
                raise LLMError("Gemini response is not valid JSON")
            return json.loads(match.group(0))

    def _request(self, *, prompt: str, response_mime_type: str = "text/plain") -> str:
        if not self.settings.gemini_api_key:
            raise LLMError("Missing GEMINI_API_KEY")

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.gemini_model}:generateContent"
            f"?key={self.settings.gemini_api_key}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "responseMimeType": response_mime_type,
            },
        }

        with httpx.Client(timeout=self.settings.gemini_timeout_sec) as client:
            response = client.post(url, json=payload)

        if response.status_code >= 400:
            raise LLMError(f"Gemini HTTP error {response.status_code}")

        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError("Gemini returned no candidates")

        content = candidates[0].get("content", {})
        parts = content.get("parts") or []
        if not parts:
            raise LLMError("Gemini returned empty content")

        text = parts[0].get("text", "").strip()
        if not text:
            raise LLMError("Gemini returned empty text")
        return text

    def _request_with_retry(self, *, prompt: str, response_mime_type: str) -> str:
        errors: list[str] = []
        for attempt in range(2):
            try:
                return self._request(prompt=prompt, response_mime_type=response_mime_type)
            except (httpx.HTTPError, LLMError, ValueError) as exc:
                errors.append(str(exc))
                if attempt == 0:
                    time.sleep(self.settings.gemini_retry_delay_sec)
        raise LLMError("; ".join(errors))

    def generate_case(self, language_mode: LanguageMode) -> dict:
        prompt = build_case_generation_prompt(language_mode)
        raw = self._request_with_retry(prompt=prompt, response_mime_type="application/json")
        return self._extract_json(raw)

    def answer_question(
        self,
        *,
        case_data: CaseFile,
        question: str,
        target: str | None,
        history: list[dict],
        language_mode: LanguageMode,
    ) -> str:
        prompt = build_answer_prompt(
            case_data=case_data,
            question=question,
            target=target,
            history=history,
            language_mode=language_mode,
        )
        return self._request_with_retry(prompt=prompt, response_mime_type="text/plain")

    def contradiction_check(
        self,
        *,
        case_data: CaseFile,
        question: str,
        answer: str,
        language_mode: LanguageMode,
    ) -> dict:
        prompt = build_contradiction_prompt(
            case_data=case_data,
            question=question,
            answer=answer,
            language_mode=language_mode,
        )
        raw = self._request_with_retry(prompt=prompt, response_mime_type="application/json")
        return self._extract_json(raw)

    def score_guess(
        self,
        *,
        case_data: CaseFile,
        guess: GuessRequest,
        language_mode: LanguageMode,
    ) -> dict | None:
        prompt = build_scoring_prompt(case_data=case_data, guess=guess, language_mode=language_mode)
        raw = self._request_with_retry(prompt=prompt, response_mime_type="application/json")
        return self._extract_json(raw)


def build_llm_client(settings: Settings) -> LLMClient:
    provider = settings.llm_provider.lower().strip()
    if provider == "gemini":
        return GeminiLLMClient(settings=settings)
    return FakeLLMClient()
