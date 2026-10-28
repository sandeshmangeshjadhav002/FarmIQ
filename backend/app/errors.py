"""Centralised error handling.

Custom exceptions carry an HTTP status code and a ``detail`` message that is
returned to the client as ``{"detail": ...}`` — matching what the existing
React frontend reads off error responses.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("farmiq.errors")


class AppError(Exception):
    def __init__(self, status_code: int, detail: str, **extra):
        self.status_code = status_code
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


class NotFoundError(AppError):
    def __init__(self, detail: str = "Resource not found."):
        super().__init__(404, detail)


class ConflictError(AppError):
    def __init__(self, detail: str = "Conflict."):
        super().__init__(409, detail)


class AuthorizationError(AppError):
    def __init__(self, detail: str = "Not authorized."):
        super().__init__(403, detail)


class ModelNotAvailableError(AppError):
    """Raised when a trained model file is not present for a given ML domain."""

    def __init__(self, detail: str):
        super().__init__(501, detail)


class InputValidationError(AppError):
    """A payload that failed *semantic* validation (outside the model's
    supported ranges, missing, or not a number).

    Distinct from FastAPI's ``RequestValidationError`` (which is about JSON
    shape/type): this is raised after the request parsed successfully but the
    values cannot honestly be fed to the model. It carries the structured
    ``errors`` (blocking) plus any ``warnings`` (unusual-but-permitted values)
    so the frontend can show exactly what to fix. Values are never clamped.
    """

    def __init__(
        self,
        detail: str,
        errors: list[dict],
        warnings: list[str] | None = None,
        advisory: list[str] | None = None,
    ):
        super().__init__(
            422,
            detail,
            errors=errors,
            warnings=warnings or [],
            advisory=advisory or [],
        )


def _sanitize_validation_errors(exc: RequestValidationError) -> list[dict]:
    """Reduce pydantic errors to JSON-safe, non-sensitive descriptors.

    Two problems are solved at once:

    * **Serialization** — pydantic v2 puts the offending *object* in ``ctx``
      (e.g. ``{"error": ValueError(...)}``) and the raw value in ``input``.
      Passing those straight to ``JSONResponse`` raises inside the handler and
      turns a 422 into a 500.
    * **Privacy** — ``input`` echoes the submitted value back and into logs,
      which would leak passwords or other fields. Only the location, machine
      ``type`` and human message are kept.
    """
    clean: list[dict] = []
    for err in exc.errors():
        item: dict = {
            "loc": [str(part) for part in err.get("loc", ())],
            "type": str(err.get("type", "value_error")),
            "msg": str(err.get("msg", "Invalid value.")),
        }
        ctx = err.get("ctx")
        if isinstance(ctx, dict):
            safe_ctx = {
                key: value
                for key, value in ctx.items()
                if value is None or isinstance(value, (str, int, float, bool))
            }
            if safe_ctx:
                item["ctx"] = safe_ctx
        clean.append(item)
    return clean


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error_handler(request: Request, exc: AppError):
        if exc.status_code >= 500:
            logger.error("AppError %s: %s", exc.status_code, exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, **exc.extra})

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError):
        errors = _sanitize_validation_errors(exc)
        # Log locations and types only — never the submitted values.
        logger.info(
            "Validation error on %s %s: %s",
            request.method,
            request.url.path,
            [{"loc": e["loc"], "type": e["type"]} for e in errors],
        )
        return JSONResponse(
            status_code=422,
            content={"detail": "Validation failed.", "errors": errors},
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error."})
