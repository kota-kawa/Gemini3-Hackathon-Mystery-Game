from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Shibuya Stream Locked-Room Mystery API"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./mystery_game.db"
    max_questions: int = 12
    llm_provider: str = "fake"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3-flash-preview"
    gemini_api_version: str = "v1beta"
    gemini_thinking_level: str = "minimal"
    gemini_retry_delay_sec: float = 0.8
    gemini_retry_max_delay_sec: float = 20.0
    gemini_max_attempts: int = 5
    gemini_fallback_to_fake: bool = False
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
