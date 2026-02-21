from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

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


logger = logging.getLogger(__name__)
RETRIABLE_GEMINI_STATUS_CODES = {408, 429, 500, 502, 503, 504}


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
        history: list[dict],
        language_mode: LanguageMode,
    ) -> str:
        q = question.lower()
        killer = next(c for c in case_data.characters if c.id == case_data.killer_id)
        mentioned_character = next(
            (character for character in case_data.characters if character.name.lower() in q),
            None,
        )

        if language_mode == LanguageMode.EN:
            unclear = "Could you narrow it down to person, timeline, or evidence?"
            spoiler_block = "I cannot reveal the final answer yet, but I can share clues."
            if any(x in q for x in ["killer", "who did it", "solution"]):
                return spoiler_block
            if mentioned_character is not None:
                if mentioned_character.is_liar:
                    lied_before = any(
                        mentioned_character.name in row.get("answer", "") and "10:12" in row.get("answer", "")
                        for row in history
                    )
                    if not lied_before:
                        return f"According to {mentioned_character.name}, they saw the victim speaking at 10:12 near the corridor."
                    return f"{mentioned_character.name} now claims they mostly stayed near the elevator hall during the blackout."
                trait = mentioned_character.traits[0] if mentioned_character.traits else "No notable trait recorded."
                return (
                    f"{mentioned_character.name}'s stated alibi is: {mentioned_character.alibi} "
                    f"Their role is {mentioned_character.role}, and a noted trait is: {trait}"
                )
            if any(x in q for x in ["evidence", "proof", "clue"]):
                first = case_data.evidence[min(len(history), len(case_data.evidence) - 1)]
                return f"One clue is '{first.name}'. {first.detail} It matters because {first.relevance}"
            if any(x in q for x in ["timeline", "time", "when"]):
                event = case_data.timeline[min(len(history), len(case_data.timeline) - 1)]
                return f"At {event.time}, {event.event}"
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
        if mentioned_character is not None:
            if mentioned_character.is_liar:
                lied_before = any(
                    mentioned_character.name in row.get("answer", "") and "10:12" in row.get("answer", "")
                    for row in history
                )
                if not lied_before:
                    return f"{mentioned_character.name}の証言では、被害者は10:12ごろ廊下で話していたそうです。"
                return f"{mentioned_character.name}は、停電中はほぼエレベーターホールにいたと言っています。"
            trait = mentioned_character.traits[0] if mentioned_character.traits else "特筆すべき特徴は記録されていません。"
            return (
                f"{mentioned_character.name}のアリバイ主張は「{mentioned_character.alibi}」です。"
                f"役割は{mentioned_character.role}で、特徴としては「{trait}」が挙げられます。"
            )
        if any(x in q for x in ["証拠", "手掛かり", "手がかり"]):
            first = case_data.evidence[min(len(history), len(case_data.evidence) - 1)]
            return f"手掛かりは『{first.name}』です。{first.detail} 重要性は、{first.relevance}"
        if any(x in q for x in ["時系列", "時間", "いつ"]):
            event = case_data.timeline[min(len(history), len(case_data.timeline) - 1)]
            return f"{event.time}の時点で、{event.event}"
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
class FallbackLLMClient(LLMClient):
    primary: LLMClient
    fallback: LLMClient

    def generate_case(self, language_mode: LanguageMode) -> dict:
        try:
            return self.primary.generate_case(language_mode)
        except (LLMError, ValueError) as exc:
            logger.warning("Primary LLM failed in generate_case. Falling back to fake provider: %s", exc)
            return self.fallback.generate_case(language_mode)

    def answer_question(
        self,
        *,
        case_data: CaseFile,
        question: str,
        history: list[dict],
        language_mode: LanguageMode,
    ) -> str:
        try:
            return self.primary.answer_question(
                case_data=case_data,
                question=question,
                history=history,
                language_mode=language_mode,
            )
        except (LLMError, ValueError) as exc:
            logger.warning("Primary LLM failed in answer_question. Falling back to fake provider: %s", exc)
            return self.fallback.answer_question(
                case_data=case_data,
                question=question,
                history=history,
                language_mode=language_mode,
            )

    def contradiction_check(
        self,
        *,
        case_data: CaseFile,
        question: str,
        answer: str,
        language_mode: LanguageMode,
    ) -> dict:
        try:
            return self.primary.contradiction_check(
                case_data=case_data,
                question=question,
                answer=answer,
                language_mode=language_mode,
            )
        except (LLMError, ValueError) as exc:
            logger.warning("Primary LLM failed in contradiction_check. Falling back to fake provider: %s", exc)
            return self.fallback.contradiction_check(
                case_data=case_data,
                question=question,
                answer=answer,
                language_mode=language_mode,
            )

    def score_guess(
        self,
        *,
        case_data: CaseFile,
        guess: GuessRequest,
        language_mode: LanguageMode,
    ) -> dict | None:
        try:
            return self.primary.score_guess(
                case_data=case_data,
                guess=guess,
                language_mode=language_mode,
            )
        except (LLMError, ValueError) as exc:
            logger.warning("Primary LLM failed in score_guess. Falling back to fake provider: %s", exc)
            return self.fallback.score_guess(
                case_data=case_data,
                guess=guess,
                language_mode=language_mode,
            )


@dataclass
class GeminiLLMClient(LLMClient):
    settings: Settings
    _client: genai.Client | None = field(default=None, init=False, repr=False)
    _supported_thinking_levels = {"minimal", "low", "medium", "high"}

    def _get_client(self) -> genai.Client:
        if not self.settings.gemini_api_key:
            raise LLMError("Missing GEMINI_API_KEY")

        if self._client is None:
            api_version = self.settings.gemini_api_version.strip()
            if api_version:
                http_options = genai_types.HttpOptions(api_version=api_version)
                self._client = genai.Client(api_key=self.settings.gemini_api_key, http_options=http_options)
            else:
                self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

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

    @staticmethod
    def _format_api_error(exc: genai_errors.APIError) -> str:
        code = getattr(exc, "code", None)
        status = getattr(exc, "status", None)
        message = getattr(exc, "message", str(exc))
        if code is None:
            return f"Gemini API error ({status}): {message}"
        return f"Gemini API error {code} ({status}): {message}"

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        text: str = ""
        try:
            candidate_text = response.text
            if isinstance(candidate_text, str):
                text = candidate_text.strip()
        except (ValueError, AttributeError):
            text = ""

        if text:
            return text

        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text.strip():
                    return part_text.strip()

        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason:
            raise LLMError(f"Gemini response blocked by safety filter: {block_reason}")
        raise LLMError("Gemini returned empty text")

    def _build_thinking_config(self) -> genai_types.ThinkingConfig | None:
        thinking_budget = self.settings.gemini_thinking_budget
        if thinking_budget is not None:
            if thinking_budget < 0:
                raise LLMError(
                    f"Invalid GEMINI_THINKING_BUDGET='{thinking_budget}'. Must be >= 0."
                )
            return genai_types.ThinkingConfig(thinking_budget=thinking_budget)

        thinking_level = (self.settings.gemini_thinking_level or "").strip().lower()
        if not thinking_level:
            return None
        if thinking_level not in self._supported_thinking_levels:
            supported = ", ".join(sorted(self._supported_thinking_levels))
            raise LLMError(f"Invalid GEMINI_THINKING_LEVEL='{thinking_level}'. Supported: {supported}")
        return genai_types.ThinkingConfig(thinking_level=thinking_level)

    def _request(
        self,
        *,
        prompt: str,
        response_mime_type: str = "text/plain",
        response_schema: type[BaseModel] | None = None,
    ) -> str:
        config_kwargs: dict[str, Any] = {
            "temperature": 0.4,
            "response_mime_type": response_mime_type,
        }
        if response_schema is not None:
            config_kwargs["response_schema"] = response_schema

        thinking_config = self._build_thinking_config()
        if thinking_config is not None:
            config_kwargs["thinking_config"] = thinking_config

        config = genai_types.GenerateContentConfig(**config_kwargs)
        response = self._get_client().models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=config,
        )
        return self._extract_response_text(response)

    def _should_retry(self, exc: genai_errors.APIError) -> bool:
        code = getattr(exc, "code", None)
        return isinstance(code, int) and code in RETRIABLE_GEMINI_STATUS_CODES

    def _next_delay_sec(self, attempt: int) -> float:
        base = max(self.settings.gemini_retry_delay_sec, 0.1)
        max_delay = max(self.settings.gemini_retry_max_delay_sec, base)
        exponential = base * (2**attempt)
        jitter = random.uniform(0, base)
        return min(exponential + jitter, max_delay)

    def _request_with_retry(
        self,
        *,
        prompt: str,
        response_mime_type: str,
        response_schema: type[BaseModel] | None = None,
    ) -> str:
        errors: list[str] = []
        max_attempts = max(1, self.settings.gemini_max_attempts)
        for attempt in range(max_attempts):
            try:
                return self._request(
                    prompt=prompt,
                    response_mime_type=response_mime_type,
                    response_schema=response_schema,
                )
            except genai_errors.APIError as exc:
                errors.append(self._format_api_error(exc))
                if attempt >= max_attempts - 1 or not self._should_retry(exc):
                    break
                delay_sec = self._next_delay_sec(attempt)
                logger.warning(
                    "Gemini request failed with retriable error (attempt %s/%s): %s. Sleeping %.2fs.",
                    attempt + 1,
                    max_attempts,
                    self._format_api_error(exc),
                    delay_sec,
                )
                time.sleep(delay_sec)
            except LLMError as exc:
                errors.append(str(exc))
                if attempt >= max_attempts - 1:
                    break
                delay_sec = self._next_delay_sec(attempt)
                logger.warning(
                    "Gemini response handling failed (attempt %s/%s): %s. Sleeping %.2fs.",
                    attempt + 1,
                    max_attempts,
                    exc,
                    delay_sec,
                )
                time.sleep(delay_sec)
            except Exception as exc:  # pragma: no cover - defensive guard
                errors.append(f"{type(exc).__name__}: {exc}")
                if attempt >= max_attempts - 1:
                    break
                delay_sec = self._next_delay_sec(attempt)
                logger.warning(
                    "Unexpected Gemini request error (attempt %s/%s): %s. Sleeping %.2fs.",
                    attempt + 1,
                    max_attempts,
                    exc,
                    delay_sec,
                )
                time.sleep(delay_sec)
        raise LLMError("; ".join(errors))

    def generate_case(self, language_mode: LanguageMode) -> dict:
        prompt = build_case_generation_prompt(language_mode)
        raw = self._request_with_retry(
            prompt=prompt,
            response_mime_type="application/json",
            response_schema=CaseFile,
        )
        return self._extract_json(raw)

    def answer_question(
        self,
        *,
        case_data: CaseFile,
        question: str,
        history: list[dict],
        language_mode: LanguageMode,
    ) -> str:
        prompt = build_answer_prompt(
            case_data=case_data,
            question=question,
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
        gemini = GeminiLLMClient(settings=settings)
        if settings.gemini_fallback_to_fake:
            return FallbackLLMClient(primary=gemini, fallback=FakeLLMClient())
        return gemini
    return FakeLLMClient()
