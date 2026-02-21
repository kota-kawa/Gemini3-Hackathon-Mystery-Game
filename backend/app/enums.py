from enum import Enum


class GameStatus(str, Enum):
    INIT = "INIT"
    PLAYING = "PLAYING"
    GUESSING = "GUESSING"
    RESULT = "RESULT"
    ENDED = "ENDED"


class LanguageMode(str, Enum):
    JA = "ja"
    EN = "en"
