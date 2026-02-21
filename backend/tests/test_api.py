import base64
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.database import Base, SessionLocal, engine
from app.enums import LanguageMode
from app.main import app, get_game_service
from app.services.game_service import GameService
from app.services.local_case_factory import build_local_case
from app.services.llm_client import GeminiLLMClient, GeneratedImage, LLMClient, LLMError
from app.services.scoring_service import ScoringService


class FailingLLMClient(LLMClient):
    def generate_case(self, language_mode):
        raise LLMError("forced failure")

    def answer_question(self, **kwargs):
        raise LLMError("forced failure")

    def contradiction_check(self, **kwargs):
        raise LLMError("forced failure")

    def score_guess(self, **kwargs):
        raise LLMError("forced failure")

    def summarize_conversation(self, **kwargs):
        raise LLMError("forced failure")


@pytest.fixture(autouse=True)
def isolate_settings_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("GEMINI_FALLBACK_TO_FAKE", "false")
    monkeypatch.setenv("GENERATED_BACKGROUND_DIR", "/tmp/mystery-game-backgrounds-tests")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def reset_db() -> Generator[None, None, None]:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app.dependency_overrides = {}
    with TestClient(app) as c:
        yield c
    app.dependency_overrides = {}


def test_full_flow_with_language_switch(client: TestClient) -> None:
    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    assert create_res.status_code == 201
    create_data = create_res.json()
    game_id = create_data["game_id"]

    lang_res = client.patch(f"/api/game/{game_id}/language", json={"language_mode": "en"})
    assert lang_res.status_code == 200
    assert lang_res.json()["language_mode"] == "en"

    ask_res = client.post(
        f"/api/game/{game_id}/ask",
        json={"question": "Show me one clue"},
    )
    assert ask_res.status_code == 200
    ask_data = ask_res.json()
    assert ask_data["remaining_questions"] == create_data["remaining_questions"] - 1
    assert isinstance(ask_data["answer_text"], str) and len(ask_data["answer_text"]) > 0
    assert isinstance(ask_data["follow_up_questions"], list)
    assert len(ask_data["follow_up_questions"]) == 3

    state_res = client.get(f"/api/game/{game_id}")
    assert state_res.status_code == 200
    state_data = state_res.json()
    assert len(state_data["messages"][0]["follow_up_questions"]) == 3
    suspect = state_data["characters"][0]["name"]

    ready_res = client.post(f"/api/game/{game_id}/ready-to-guess")
    assert ready_res.status_code == 204

    guess_res = client.post(
        f"/api/game/{game_id}/guess",
        json={
            "killer": suspect,
            "motive": "financial pressure",
            "method": "delayed gas release",
            "trick": "magnetic latch reset",
            "reasoning": "blackout timing and evidence line up",
        },
    )
    assert guess_res.status_code == 200
    guess_data = guess_res.json()
    assert 0 <= guess_data["score"] <= 100
    assert guess_data["grade"] in ["S", "A", "B", "C"]
    assert len(guess_data["weaknesses_top3"]) == 3


def test_ask_invalid_state_returns_409(client: TestClient) -> None:
    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    game_id = create_res.json()["game_id"]

    client.post(f"/api/game/{game_id}/ready-to-guess")
    ask_res = client.post(
        f"/api/game/{game_id}/ask",
        json={"question": "証拠は?"},
    )

    assert ask_res.status_code == 409
    assert ask_res.json()["error_code"] == "INVALID_STATE"


def test_ask_character_info_without_target_field(client: TestClient) -> None:
    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    assert create_res.status_code == 201
    game_id = create_res.json()["game_id"]

    state_res = client.get(f"/api/game/{game_id}")
    assert state_res.status_code == 200
    character_name = state_res.json()["characters"][0]["name"]

    ask_res = client.post(
        f"/api/game/{game_id}/ask",
        json={"question": f"{character_name}のアリバイを教えて"},
    )
    assert ask_res.status_code == 200
    assert character_name in ask_res.json()["answer_text"]
    assert len(ask_res.json()["follow_up_questions"]) == 3


def test_ask_where_were_you_answer_has_explicit_actor_name(client: TestClient) -> None:
    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    assert create_res.status_code == 201
    game_id = create_res.json()["game_id"]

    state_res = client.get(f"/api/game/{game_id}")
    assert state_res.status_code == 200
    names = [character["name"] for character in state_res.json()["characters"]]

    ask_res = client.post(
        f"/api/game/{game_id}/ask",
        json={"question": "事件当時、あなたはどこにいた？"},
    )
    assert ask_res.status_code == 200
    answer_text = ask_res.json()["answer_text"]
    assert any(name in answer_text for name in names)
    assert "私は" not in answer_text


def test_guess_invalid_state_returns_409(client: TestClient) -> None:
    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    game_id = create_res.json()["game_id"]

    guess_res = client.post(
        f"/api/game/{game_id}/guess",
        json={
            "killer": "X",
            "motive": "X",
            "method": "X",
            "trick": "X",
            "reasoning": "X",
        },
    )

    assert guess_res.status_code == 409
    assert guess_res.json()["error_code"] == "INVALID_STATE"


def test_invalid_language_returns_400(client: TestClient) -> None:
    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    game_id = create_res.json()["game_id"]

    res = client.patch(f"/api/game/{game_id}/language", json={"language_mode": "fr"})
    assert res.status_code == 400
    assert res.json()["error_code"] == "INVALID_REQUEST"


def test_ask_succeeds_when_contradiction_check_fails(client: TestClient) -> None:
    class ContradictionFailingLLMClient(LLMClient):
        def generate_case(self, language_mode: LanguageMode):
            return build_local_case(language_mode)

        def answer_question(self, **kwargs):
            return "停電の空白時間をまず確認してください。"

        def contradiction_check(self, **kwargs):
            raise LLMError("forced contradiction failure")

        def score_guess(self, **kwargs):
            return None

        def summarize_conversation(self, **kwargs):
            return {
                "killer": "会話からは不明",
                "method": "会話からは不明",
                "motive": "会話からは不明",
                "trick": "会話からは不明",
                "highlights": ["停電の空白時間をまず確認してください。"],
            }

    def override_game_service() -> GameService:
        db = SessionLocal()
        return GameService(
            db=db,
            llm_client=ContradictionFailingLLMClient(),
            scoring_service=ScoringService(),
            settings=get_settings(),
        )

    app.dependency_overrides[get_game_service] = override_game_service

    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    assert create_res.status_code == 201
    game_id = create_res.json()["game_id"]

    ask_res = client.post(
        f"/api/game/{game_id}/ask",
        json={"question": "手掛かりは?"},
    )
    assert ask_res.status_code == 200
    assert "停電の空白時間" in ask_res.json()["answer_text"]
    assert len(ask_res.json()["follow_up_questions"]) == 3

    app.dependency_overrides = {}


def test_gemini_provider_falls_back_to_fake(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def override_settings() -> Settings:
        return Settings(
            llm_provider="gemini",
            gemini_api_key="dummy-key",
            gemini_fallback_to_fake=True,
        )

    def force_gemini_failure(self, *, prompt: str, response_mime_type: str, response_schema=None) -> str:
        raise LLMError("forced gemini failure")

    def force_gemini_image_failure(self, *, prompt: str):
        raise LLMError("forced gemini image failure")

    monkeypatch.setattr(GeminiLLMClient, "_request_with_retry", force_gemini_failure)
    monkeypatch.setattr(GeminiLLMClient, "_request_background_image_with_retry", force_gemini_image_failure)
    app.dependency_overrides[get_settings] = override_settings

    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    assert create_res.status_code == 201
    game_id = create_res.json()["game_id"]

    ask_res = client.post(
        f"/api/game/{game_id}/ask",
        json={"question": "証拠を1つ教えて"},
    )
    assert ask_res.status_code == 200
    assert isinstance(ask_res.json()["answer_text"], str)
    assert len(ask_res.json()["follow_up_questions"]) == 3


def test_gemini_failure_returns_502(client: TestClient) -> None:
    def override_game_service() -> GameService:
        db = SessionLocal()
        return GameService(
            db=db,
            llm_client=FailingLLMClient(),
            scoring_service=ScoringService(),
            settings=get_settings(),
        )

    app.dependency_overrides[get_game_service] = override_game_service

    res = client.post("/api/game/new", json={"language_mode": "ja"})
    assert res.status_code == 502
    body = res.json()
    assert body["error_code"] == "GEMINI_UNAVAILABLE"
    assert body["retryable"] is True

    app.dependency_overrides = {}


def test_conversation_summary_endpoint(client: TestClient) -> None:
    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    assert create_res.status_code == 201
    game_id = create_res.json()["game_id"]

    ask_res = client.post(
        f"/api/game/{game_id}/ask",
        json={"question": "証拠を1つ教えて"},
    )
    assert ask_res.status_code == 200

    summary_res = client.post(f"/api/game/{game_id}/summarize")
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert "killer" in summary
    assert "method" in summary
    assert "motive" in summary
    assert "trick" in summary
    assert isinstance(summary["highlights"], list)


def test_background_endpoint_returns_generated_image(client: TestClient) -> None:
    class ImageGeneratingLLMClient(LLMClient):
        def generate_case(self, language_mode: LanguageMode):
            return build_local_case(language_mode)

        def answer_question(self, **kwargs):
            return "手掛かりを照合してください。"

        def contradiction_check(self, **kwargs):
            return {"contradiction": False, "fixed_answer": "手掛かりを照合してください。"}

        def score_guess(self, **kwargs):
            return None

        def summarize_conversation(self, **kwargs):
            return {
                "killer": "会話からは不明",
                "method": "会話からは不明",
                "motive": "会話からは不明",
                "trick": "会話からは不明",
                "highlights": ["手掛かりを照合してください。"],
            }

        def generate_background_image(self, **kwargs):
            png_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7+f0UAAAAASUVORK5CYII="
            )
            return GeneratedImage(data=png_bytes, mime_type="image/png")

        def generate_result_background_image(self, **kwargs):
            png_bytes = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAwUBAO5+Qp8AAAAASUVORK5CYII="
            )
            return GeneratedImage(data=png_bytes, mime_type="image/png")

    def override_game_service() -> GameService:
        db = SessionLocal()
        return GameService(
            db=db,
            llm_client=ImageGeneratingLLMClient(),
            scoring_service=ScoringService(),
            settings=get_settings(),
        )

    app.dependency_overrides[get_game_service] = override_game_service

    create_res = client.post("/api/game/new", json={"language_mode": "ja"})
    assert create_res.status_code == 201
    game_id = create_res.json()["game_id"]
    assert create_res.json()["background_image_url"] == f"/api/game/{game_id}/background"

    state_res = client.get(f"/api/game/{game_id}")
    assert state_res.status_code == 200
    assert state_res.json()["background_image_url"] == f"/api/game/{game_id}/background"
    assert state_res.json()["result_background_image_url"] is None

    bg_res = client.get(f"/api/game/{game_id}/background")
    assert bg_res.status_code == 200
    assert bg_res.headers["content-type"].startswith("image/png")
    assert len(bg_res.content) > 0

    ready_res = client.post(f"/api/game/{game_id}/ready-to-guess")
    assert ready_res.status_code == 204

    suspect = state_res.json()["characters"][0]["name"]
    guess_res = client.post(
        f"/api/game/{game_id}/guess",
        json={
            "killer": suspect,
            "motive": "financial pressure",
            "method": "delayed gas release",
            "trick": "magnetic latch reset",
            "reasoning": "blackout timing and evidence line up",
        },
    )
    assert guess_res.status_code == 200
    assert guess_res.json()["result_background_image_url"] == f"/api/game/{game_id}/result-background"

    result_state_res = client.get(f"/api/game/{game_id}")
    assert result_state_res.status_code == 200
    assert result_state_res.json()["result_background_image_url"] == f"/api/game/{game_id}/result-background"

    result_bg_res = client.get(f"/api/game/{game_id}/result-background")
    assert result_bg_res.status_code == 200
    assert result_bg_res.headers["content-type"].startswith("image/png")
    assert len(result_bg_res.content) > 0

    app.dependency_overrides = {}
