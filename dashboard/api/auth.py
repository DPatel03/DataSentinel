"""Optional Bearer-token auth for the dashboard API."""

from __future__ import annotations

import hmac
import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from validation.config import load_env

PUBLIC_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}


def dashboard_auth_token() -> str:
    load_env()
    return os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()


def _authorized(request: Request, token: str) -> bool:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False
    provided = header[7:].strip()
    return hmac.compare_digest(provided, token)


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)
        token = dashboard_auth_token()
        if not token:
            return await call_next(request)
        path = request.url.path
        if path in PUBLIC_PATHS or not path.startswith("/api"):
            return await call_next(request)
        if _authorized(request, token):
            return await call_next(request)
        return JSONResponse(
            {"detail": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
