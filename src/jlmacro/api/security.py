"""Optional API-key authentication.

This API has no auth by default (`jlmacro_api_key` unset) - fine for local
development against a database only reachable from `localhost`, never for a
deployment reachable from anywhere else. Set `JLMACRO_API_KEY` before exposing this
API beyond localhost; every request then must carry a matching `X-API-Key` header,
checked with a constant-time comparison so response timing can't be used to guess
the key one byte at a time. `/health` and the auto-generated docs routes stay
unauthenticated even when a key is configured, since infrastructure health checks
and interactive API exploration shouldn't need a live key just to load.
"""

from __future__ import annotations

import hmac

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from jlmacro.config import get_settings

_EXEMPT_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        settings = get_settings()
        expected_key = settings.jlmacro_api_key

        if not expected_key or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        provided_key = request.headers.get("x-api-key", "")
        if not hmac.compare_digest(provided_key, expected_key):
            return JSONResponse(status_code=401, content={"detail": "invalid or missing X-API-Key"})

        return await call_next(request)
