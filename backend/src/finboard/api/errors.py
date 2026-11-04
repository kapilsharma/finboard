"""Every error leaves the API as RFC 9457 problem+json with a stable `code`."""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from finboard.domain.errors import (
    Conflict,
    FinboardError,
    NotFound,
    PayloadTooLarge,
    ServiceUnavailable,
    Unauthenticated,
    ValidationFailed,
)

log = structlog.get_logger(__name__)

PROBLEM_JSON = "application/problem+json"

_STATUS: dict[type[FinboardError], int] = {
    NotFound: 404,
    Conflict: 409,
    ValidationFailed: 422,
    Unauthenticated: 401,
    ServiceUnavailable: 503,
    PayloadTooLarge: 413,
}


def problem(
    status: int, code: str, title: str, detail: str | None = None, **extra: Any
) -> JSONResponse:
    body = {"type": "about:blank", "status": status, "code": code, "title": title}
    if detail:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(jsonable_encoder(body), status_code=status, media_type=PROBLEM_JSON)


def _status_for(exc: FinboardError) -> int:
    for cls in type(exc).__mro__:
        if cls in _STATUS:
            return _STATUS[cls]
    return 400


async def _domain_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, FinboardError)
    return problem(_status_for(exc), exc.code, exc.title, exc.detail)


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]
    return problem(422, "invalid_request", "Invalid request", errors=errors)


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return problem(exc.status_code, "http_error", str(exc.detail))


async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("request.unhandled_error", error=type(exc).__name__)
    return problem(500, "internal_error", "Internal error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(FinboardError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
