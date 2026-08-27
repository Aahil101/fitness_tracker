"""Shared exception types and a consistent JSON error envelope."""

from __future__ import annotations

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class AppError(HTTPException):
    """Base error carrying a stable machine-readable code."""

    code = "app_error"

    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> None:
        super().__init__(status_code=status_code, detail=detail)


class ConfigurationError(AppError):
    code = "configuration_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail, status.HTTP_503_SERVICE_UNAVAILABLE)


class AuthError(AppError):
    code = "unauthorized"

    def __init__(self, detail: str = "Not authenticated") -> None:
        super().__init__(detail, status.HTTP_401_UNAUTHORIZED)


class NotFoundError(AppError):
    code = "not_found"

    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(detail, status.HTTP_404_NOT_FOUND)


class RateLimitError(AppError):
    code = "rate_limited"

    def __init__(self, detail: str = "Rate limit exceeded", retry_after: int = 60) -> None:
        super().__init__(detail, status.HTTP_429_TOO_MANY_REQUESTS)
        self.retry_after = retry_after


class UpstreamError(AppError):
    code = "upstream_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail, status.HTTP_502_BAD_GATEWAY)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    headers = {}
    if isinstance(exc, RateLimitError):
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.detail}},
        headers=headers,
    )


async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "http_error", "message": exc.detail}},
        headers=getattr(exc, "headers", None),
    )
