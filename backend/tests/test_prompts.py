from datetime import datetime

from app.enums import LanguageMode
from app.schemas import CaseFile, GuessRequest
from app.services.local_case_factory import build_local_case
from app.services.prompts import (
    _current_datetime_instruction,
    build_answer_prompt,
    build_background_prompt,
    build_case_generation_prompt,
    build_conversation_summary_prompt,
    build_contradiction_prompt,
    build_scoring_prompt,
)


def _sample_case(language_mode: LanguageMode) -> CaseFile:
    return CaseFile.model_validate(build_local_case(language_mode))


def test_current_datetime_instruction_formats_ja_and_en() -> None:
    fixed_now = datetime(2026, 2, 21, 9, 30, 0)
    assert _current_datetime_instruction(LanguageMode.JA, fixed_now) == "現在日時: 2026年2月21日（土曜日）。"
    assert _current_datetime_instruction(LanguageMode.EN, fixed_now) == "Current date and weekday: 2026-02-21 (Saturday)."


def test_case_generation_prompt_includes_current_date_line() -> None:
    fixed_now = datetime(2026, 2, 21, 9, 30, 0)
    prompt = build_case_generation_prompt(LanguageMode.JA, now=fixed_now)
    assert "現在日時: 2026年2月21日（土曜日）。" in prompt


def test_answer_prompt_includes_current_date_line() -> None:
    fixed_now = datetime(2026, 2, 21, 9, 30, 0)
    case_data = _sample_case(LanguageMode.EN)
    prompt = build_answer_prompt(
        case_data=case_data,
        question="What clue do we have?",
        history=[],
        language_mode=LanguageMode.EN,
        now=fixed_now,
    )
    assert "Current date and weekday: 2026-02-21 (Saturday)." in prompt
    assert "<FOLLOW_UP_QUESTIONS>" in prompt
    assert "</FOLLOW_UP_QUESTIONS>" in prompt
    assert "Never answer in first person" in prompt
    assert "Always make actor and action explicit" in prompt


def test_contradiction_and_scoring_prompts_include_current_date_line() -> None:
    fixed_now = datetime(2026, 2, 21, 9, 30, 0)
    case_data = _sample_case(LanguageMode.EN)
    contradiction_prompt = build_contradiction_prompt(
        case_data=case_data,
        question="Is this consistent?",
        answer="Yes.",
        language_mode=LanguageMode.EN,
        now=fixed_now,
    )
    assert "Current date and weekday: 2026-02-21 (Saturday)." in contradiction_prompt

    guess = GuessRequest(
        killer=case_data.characters[0].name,
        motive="money pressure",
        method="delayed gas release",
        trick="latch timer",
        reasoning="timeline and evidence align",
    )
    scoring_prompt = build_scoring_prompt(
        case_data=case_data,
        guess=guess,
        language_mode=LanguageMode.EN,
        now=fixed_now,
    )
    assert "Current date and weekday: 2026-02-21 (Saturday)." in scoring_prompt


def test_conversation_summary_prompt_includes_current_date_line() -> None:
    fixed_now = datetime(2026, 2, 21, 9, 30, 0)
    prompt = build_conversation_summary_prompt(
        history=[{"question": "Who is suspicious?", "answer": "Check the blackout window."}],
        language_mode=LanguageMode.EN,
        now=fixed_now,
    )
    assert "Current date and weekday: 2026-02-21 (Saturday)." in prompt
    assert "killer, method, motive, trick, highlights" in prompt


def test_background_prompt_mentions_story_context_and_ratio() -> None:
    case_data = _sample_case(LanguageMode.JA)
    prompt = build_background_prompt(case_data=case_data, language_mode=LanguageMode.JA)
    assert case_data.setting.location in prompt
    assert case_data.setting.time_window in prompt
    assert "9:16" in prompt
