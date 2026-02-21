from app.enums import LanguageMode
from app.schemas import CaseFile
from app.services.local_case_factory import build_local_case
from app.services.follow_up import append_follow_up_block, split_answer_and_follow_up_questions


def test_split_answer_and_follow_up_questions_extracts_block() -> None:
    raw = (
        "停電の空白時間を確認してください。\n\n"
        "<FOLLOW_UP_QUESTIONS>\n"
        "Q1: 最後に被害者を見たのは誰？\n"
        "Q2: 事件当時、あなたはどこにいた？\n"
        "Q3: 被害者と揉めていた人物はいる？\n"
        "</FOLLOW_UP_QUESTIONS>"
    )
    answer, followups = split_answer_and_follow_up_questions(raw, language_mode=LanguageMode.JA)
    assert answer == "停電の空白時間を確認してください。"
    assert len(followups) == 3
    assert followups[0] == "最後に被害者を見たのは誰？"


def test_split_answer_and_follow_up_questions_uses_default_when_missing() -> None:
    answer, followups = split_answer_and_follow_up_questions(
        "証言時刻の食い違いを追ってください。",
        language_mode=LanguageMode.JA,
    )
    assert answer == "証言時刻の食い違いを追ってください。"
    assert len(followups) == 3


def test_append_follow_up_block_round_trip() -> None:
    wrapped = append_follow_up_block(
        answer_text="Focus on witness timing.",
        questions=[
            "Who saw the victim last?",
            "Where were you when it happened?",
            "Who had conflict with the victim?",
        ],
        language_mode=LanguageMode.EN,
    )
    answer, followups = split_answer_and_follow_up_questions(wrapped, language_mode=LanguageMode.EN)
    assert answer == "Focus on witness timing."
    assert len(followups) == 3


def test_heuristic_follow_ups_are_contextual() -> None:
    from app.services.follow_up import heuristic_follow_up_questions

    case_data = CaseFile.model_validate(build_local_case(LanguageMode.JA))
    followups = heuristic_follow_up_questions(
        case_data=case_data,
        language_mode=LanguageMode.JA,
        history_count=2,
    )
    assert len(followups) == 3
    assert case_data.evidence[2].name in followups[0] or case_data.victim.name in followups[0]
