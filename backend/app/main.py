from fastapi import Body, Depends, FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db, init_db
from .errors import AppError, app_error_handler, unhandled_error_handler, validation_error_handler
from .schemas import (
    AskRequest,
    AskResponse,
    ConversationSummaryResponse,
    ErrorResponse,
    GameStateResponse,
    GuessRequest,
    GuessResponse,
    NewGameRequest,
    NewGameResponse,
    PatchLanguageRequest,
    PatchLanguageResponse,
)
from .services.game_service import GameService
from .services.llm_client import build_llm_client
from .services.scoring_service import ScoringService


app = FastAPI(title="Locked-Room Mystery API", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.get("/health")
def healthcheck() -> dict:
    return {"ok": True}


def get_game_service(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> GameService:
    llm_client = build_llm_client(settings)
    scoring_service = ScoringService()
    return GameService(db=db, llm_client=llm_client, scoring_service=scoring_service, settings=settings)


@app.post(
    "/api/game/new",
    response_model=NewGameResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def create_game(
    body: NewGameRequest = Body(default_factory=NewGameRequest),
    service: GameService = Depends(get_game_service),
) -> NewGameResponse:
    return service.create_game(body.language_mode)


@app.get(
    "/api/game/{game_id}",
    response_model=GameStateResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_game(
    game_id: str,
    service: GameService = Depends(get_game_service),
) -> GameStateResponse:
    return service.get_game(game_id)


@app.post(
    "/api/game/{game_id}/ask",
    response_model=AskResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
def ask_question(
    game_id: str,
    body: AskRequest,
    service: GameService = Depends(get_game_service),
) -> AskResponse:
    result = service.ask(game_id, body)
    return AskResponse(**result)


@app.post(
    "/api/game/{game_id}/summarize",
    response_model=ConversationSummaryResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
def summarize_conversation(
    game_id: str,
    service: GameService = Depends(get_game_service),
) -> ConversationSummaryResponse:
    return service.summarize_conversation(game_id)


@app.post(
    "/api/game/{game_id}/guess",
    response_model=GuessResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def submit_guess(
    game_id: str,
    body: GuessRequest,
    service: GameService = Depends(get_game_service),
) -> GuessResponse:
    result = service.submit_guess(game_id, body)
    return GuessResponse(**result)


@app.patch(
    "/api/game/{game_id}/language",
    response_model=PatchLanguageResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def patch_language(
    game_id: str,
    body: PatchLanguageRequest,
    service: GameService = Depends(get_game_service),
) -> PatchLanguageResponse:
    return service.patch_language(game_id, body.language_mode)


@app.post(
    "/api/game/{game_id}/ready-to-guess",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def ready_to_guess(
    game_id: str,
    service: GameService = Depends(get_game_service),
) -> None:
    service.move_to_guessing(game_id)


@app.post(
    "/api/game/{game_id}/end",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorResponse}},
)
def end_game(game_id: str, service: GameService = Depends(get_game_service)) -> None:
    service.end_game(game_id)


@app.get(
    "/api/game/{game_id}/background",
    responses={404: {"model": ErrorResponse}},
)
def get_game_background(
    game_id: str,
    service: GameService = Depends(get_game_service),
) -> FileResponse:
    image_path, media_type = service.get_background_asset(game_id)
    return FileResponse(image_path, media_type=media_type)


@app.get(
    "/api/game/{game_id}/result-background",
    responses={404: {"model": ErrorResponse}},
)
def get_game_result_background(
    game_id: str,
    service: GameService = Depends(get_game_service),
) -> FileResponse:
    image_path, media_type = service.get_result_background_asset(game_id)
    return FileResponse(image_path, media_type=media_type)
