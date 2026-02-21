from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.main import app, get_game_service
from app.services.game_service import GameService
from app.services.llm_client import LLMClient, LLMError
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
        json={"question": "Show me one clue", "target": "overall"},
    )
    assert ask_res.status_code == 200
    ask_data = ask_res.json()
    assert ask_data["remaining_questions"] == create_data["remaining_questions"] - 1
    assert isinstance(ask_data["answer_text"], str) and len(ask_data["answer_text"]) > 0

    state_res = client.get(f"/api/game/{game_id}")
    assert state_res.status_code == 200
    state_data = state_res.json()
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
