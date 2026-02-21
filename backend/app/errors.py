from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .schemas import ErrorResponse


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        retryable: bool = False,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        self.detail = detail or {}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    payload = ErrorResponse(
        error_code=exc.error_code,
        message=exc.message,
        retryable=exc.retryable,
        detail=exc.detail,
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    payload = ErrorResponse(
        error_code="INVALID_REQUEST",
        message="入力内容を確認してください。",
        retryable=False,
        detail={"issues": exc.errors()},
    )
    return JSONResponse(status_code=400, content=payload.model_dump())


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    payload = ErrorResponse(
        error_code="INTERNAL_ERROR",
        message="予期しないエラーが発生しました。",
        retryable=False,
        detail={"type": type(exc).__name__},
    )
    return JSONResponse(status_code=500, content=payload.model_dump())


def bad_request(message: str, detail: dict | None = None) -> AppError:
    return AppError(
        status_code=400,
        error_code="BAD_REQUEST",
        message=message,
        retryable=False,
        detail=detail,
    )


def not_found(message: str, detail: dict | None = None) -> AppError:
    return AppError(
        status_code=404,
        error_code="NOT_FOUND",
        message=message,
        retryable=False,
        detail=detail,
    )


def conflict(message: str, detail: dict | None = None) -> AppError:
    return AppError(
        status_code=409,
        error_code="INVALID_STATE",
        message=message,
        retryable=False,
        detail=detail,
    )


def gemini_error(message: str, detail: dict | None = None) -> AppError:
    return AppError(
        status_code=502,
        error_code="GEMINI_UNAVAILABLE",
        message=message,
        retryable=True,
        detail=detail,
    )
