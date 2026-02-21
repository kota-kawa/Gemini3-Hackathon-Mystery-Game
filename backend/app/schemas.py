from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import GameStatus, LanguageMode


class Character(BaseModel):
    id: str
    name: str
    role: str
    traits: list[str] = Field(default_factory=list)
    alibi: str
    secrets: list[str] = Field(default_factory=list)
    is_liar: bool = False
    is_killer: bool = False


class Victim(BaseModel):
    id: str
    name: str
    occupation: str
    cause_of_death: str
    found_state: str


class TimelineEvent(BaseModel):
    time: str
    event: str


class EvidenceItem(BaseModel):
    id: str
    name: str
    detail: str
    relevance: str


class TruthBlock(BaseModel):
    solution: str
    why_room_was_locked: str
    how_alibi_was_faked: str


class GmRules(BaseModel):
    disclosure_policy: str
    liar_policy: str
    safety: str


class SettingInfo(BaseModel):
    location: str
    time_window: str
    summary: str


class CaseFile(BaseModel):
    case_id: str
    title: str
    setting: SettingInfo
    characters: list[Character]
    victim: Victim
    killer_id: str
    liar_id: str
    motive: str
    method: str
    trick: str
    timeline: list[TimelineEvent]
    evidence: list[EvidenceItem]
    truth: TruthBlock
    gm_rules: GmRules

    @field_validator("characters")
    @classmethod
    def validate_characters_count(cls, value: list[Character]) -> list[Character]:
        if not 4 <= len(value) <= 6:
            raise ValueError("characters must include 4 to 6 members")
        return value

    @field_validator("evidence")
    @classmethod
    def validate_evidence_count(cls, value: list[EvidenceItem]) -> list[EvidenceItem]:
        if len(value) < 5:
            raise ValueError("evidence must include at least 5 items")
        return value

    @model_validator(mode="after")
    def validate_roles(self) -> "CaseFile":
        character_ids = {character.id for character in self.characters}
        if self.killer_id not in character_ids:
            raise ValueError("killer_id must exist in characters")
        if self.liar_id not in character_ids:
            raise ValueError("liar_id must exist in characters")
        if self.killer_id == self.liar_id:
            raise ValueError("liar_id and killer_id must be different")

        liar_count = sum(1 for c in self.characters if c.is_liar)
        killer_count = sum(1 for c in self.characters if c.is_killer)

        if liar_count != 1 or killer_count != 1:
            raise ValueError("exactly one liar and one killer flag are required")

        liar_obj = next(c for c in self.characters if c.id == self.liar_id)
        killer_obj = next(c for c in self.characters if c.id == self.killer_id)
        if not liar_obj.is_liar:
            raise ValueError("liar_id does not match character marked as liar")
        if not killer_obj.is_killer:
            raise ValueError("killer_id does not match character marked as killer")

        return self


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    retryable: bool
    detail: dict = Field(default_factory=dict)


class NewGameRequest(BaseModel):
    language_mode: LanguageMode = LanguageMode.JA


class CaseSummaryResponse(BaseModel):
    title: str
    location: str
    time_window: str
    summary: str
    victim_name: str
    found_state: str


class CharacterPublicResponse(BaseModel):
    id: str
    name: str
    role: str
    traits: list[str]


class NewGameResponse(BaseModel):
    game_id: str
    case_summary: CaseSummaryResponse
    characters: list[CharacterPublicResponse]
    initial_state: GameStatus
    remaining_questions: int
    language_mode: LanguageMode


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class UnlockedEvidenceResponse(BaseModel):
    id: str
    name: str
    detail: str
    relevance: str


class AskResponse(BaseModel):
    answer_text: str
    remaining_questions: int
    status: GameStatus
    unlocked_evidence: UnlockedEvidenceResponse | None = None


class GuessRequest(BaseModel):
    killer: str = Field(min_length=1, max_length=255)
    motive: str = Field(min_length=1, max_length=1000)
    method: str = Field(min_length=1, max_length=1000)
    trick: str = Field(min_length=1, max_length=1000)
    reasoning: str = Field(min_length=1, max_length=2000)


class MatchResult(BaseModel):
    killer: bool
    motive: bool
    method: bool
    trick: bool


class GuessResponse(BaseModel):
    score: int
    grade: Literal["S", "A", "B", "C"]
    matches: MatchResult
    feedback: str
    contradictions: list[str]
    weaknesses_top3: list[str]
    solution_summary: str


class PatchLanguageRequest(BaseModel):
    language_mode: LanguageMode


class PatchLanguageResponse(BaseModel):
    game_id: str
    language_mode: LanguageMode


class MessageResponse(BaseModel):
    id: int
    question: str
    answer_text: str
    language_mode: LanguageMode
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GameStateResponse(BaseModel):
    game_id: str
    status: GameStatus
    remaining_questions: int
    language_mode: LanguageMode
    case_summary: CaseSummaryResponse
    characters: list[CharacterPublicResponse]
    unlocked_evidence: list[UnlockedEvidenceResponse]
    messages: list[MessageResponse]
