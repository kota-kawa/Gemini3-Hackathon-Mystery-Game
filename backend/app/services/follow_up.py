from __future__ import annotations

import re

from ..enums import LanguageMode
from ..schemas import CaseFile


FOLLOW_UP_OPEN_TAG = "<FOLLOW_UP_QUESTIONS>"
FOLLOW_UP_CLOSE_TAG = "</FOLLOW_UP_QUESTIONS>"
_FOLLOW_UP_BLOCK_RE = re.compile(
    rf"{re.escape(FOLLOW_UP_OPEN_TAG)}\s*(.*?)\s*{re.escape(FOLLOW_UP_CLOSE_TAG)}",
    re.DOTALL,
)


def default_follow_up_questions(language_mode: LanguageMode) -> list[str]:
    if language_mode == LanguageMode.EN:
        return [
            "Who saw the victim last?",
            "Where were you when it happened?",
            "Who had conflict with the victim?",
        ]
    return [
        "最後に被害者を見たのは誰？",
        "事件当時、あなたはどこにいた？",
        "被害者と揉めていた人物はいる？",
    ]


def heuristic_follow_up_questions(
    *,
    case_data: CaseFile,
    language_mode: LanguageMode,
    history_count: int,
) -> list[str]:
    evidence = case_data.evidence[min(history_count, len(case_data.evidence) - 1)]
    timeline_event = case_data.timeline[min(history_count, len(case_data.timeline) - 1)]
    victim_name = case_data.victim.name
    rotation = history_count % 4

    if language_mode == LanguageMode.EN:
        candidates = [
            f"Who was near {victim_name} around {timeline_event.time}?",
            f"Who had the strongest conflict or benefit tied to {victim_name}?",
            f"How does the evidence '{evidence.name}' narrow the murder method?",
            "What concrete steps could create the locked-room trick here?",
        ]
    else:
        candidates = [
            f"{timeline_event.time}前後に{victim_name}の近くにいた人物は誰？",
            f"{victim_name}と利害対立が最も強かった人物は誰？",
            f"証拠「{evidence.name}」はどの手口を裏づける？",
            "この現場で密室トリックを成立させる具体的な手順は？",
        ]

    ordered = [candidates[(rotation + offset) % len(candidates)] for offset in range(3)]
    return ordered


def _normalize_follow_up_questions(
    questions: list[str],
    *,
    language_mode: LanguageMode,
    with_default: bool,
) -> list[str]:
    cleaned: list[str] = []
    for question in questions:
        line = question.strip()
        if not line:
            continue
        line = re.sub(r"^(?:Q?\s*\d+\s*[:.)\-]\s*)", "", line, flags=re.IGNORECASE)
        line = line.strip(" ・-")
        if not line:
            continue
        if line not in cleaned:
            cleaned.append(line)
        if len(cleaned) >= 3:
            break

    if not with_default:
        return cleaned[:3]

    fallback = default_follow_up_questions(language_mode)
    for question in fallback:
        if len(cleaned) >= 3:
            break
        if question not in cleaned:
            cleaned.append(question)
    return cleaned[:3]


def append_follow_up_block(
    answer_text: str,
    questions: list[str],
    *,
    language_mode: LanguageMode,
) -> str:
    normalized_questions = _normalize_follow_up_questions(
        questions,
        language_mode=language_mode,
        with_default=False,
    )
    body = answer_text.strip()
    follow_up_lines = [f"Q{index + 1}: {question}" for index, question in enumerate(normalized_questions)]

    if not body:
        body = "..."

    return "\n".join(
        [
            body,
            "",
            FOLLOW_UP_OPEN_TAG,
            *follow_up_lines,
            FOLLOW_UP_CLOSE_TAG,
        ]
    )


def split_answer_and_follow_up_questions(
    raw_answer_text: str,
    *,
    language_mode: LanguageMode,
    with_default: bool = True,
) -> tuple[str, list[str]]:
    raw_text = raw_answer_text or ""
    match = _FOLLOW_UP_BLOCK_RE.search(raw_text)
    if match is None:
        answer_text = raw_text.strip()
        return (
            answer_text,
            _normalize_follow_up_questions(
                [],
                language_mode=language_mode,
                with_default=with_default,
            ),
        )

    block = match.group(1)
    questions = [line.strip() for line in block.splitlines() if line.strip()]
    normalized_questions = _normalize_follow_up_questions(
        questions,
        language_mode=language_mode,
        with_default=with_default,
    )

    answer_text = f"{raw_text[: match.start()]}{raw_text[match.end() :]}".strip()
    return answer_text, normalized_questions
