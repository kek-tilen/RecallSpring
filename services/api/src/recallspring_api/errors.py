"""Standard error envelope ``{code, message, request_id, details?}`` (docs/07)."""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("recallspring.errors")

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def not_found(entity: str) -> ApiError:
    return ApiError(404, "not_found", f"{entity} not found.")


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id_var.get()}
    if details:
        body["details"] = details
    return body


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get("x-request-id", "")
        try:
            rid = str(uuid.UUID(incoming))
        except ValueError:
            rid = str(uuid.uuid4())
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Report field locations and error types only; never echo submitted values (may contain learner text).
        problems = [{"loc": list(e.get("loc", [])), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(
            error_body("invalid_request", "The request is invalid.", {"problems": problems}), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(error_body("http_error", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error request_id=%s", request_id_var.get())
        return JSONResponse(
            error_body("internal_error", "Something went wrong. Nothing unsaved was lost."), status_code=500
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(DBAPIError)
    async def storage_error_handler(_: Request, exc: Exception) -> JSONResponse:
        # Fail closed: never acknowledge a save the database did not confirm (FR-09, T-24).
        log.error("storage error (%s) request_id=%s", type(exc).__name__, request_id_var.get())
        return JSONResponse(
            error_body("storage_unavailable", "Storage is unavailable. Nothing was saved; please retry."),
            status_code=503,
        )
