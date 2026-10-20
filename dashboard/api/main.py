"""FastAPI application entrypoint for DataSentinel dashboard."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from dashboard.api.auth import DashboardAuthMiddleware
from dashboard.api.routes import router

app = FastAPI(title="DataSentinel Dashboard API", version="1.2.0")

_raw_origins = os.getenv("DASHBOARD_CORS_ORIGINS", "http://localhost:3000")
_origins = [origin.strip() for origin in _raw_origins.split(",") if origin.strip()]
_wildcard = _origins == ["*"]

# Last added middleware is outermost. CORS must wrap auth so preflight succeeds.
app.add_middleware(DashboardAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _wildcard else _origins,
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

# Serve built React frontend if present
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
