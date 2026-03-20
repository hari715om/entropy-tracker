"""
FastAPI application — main entry point for the Entropy API.

Provides:
- CORS middleware for dashboard
- Router includes for repos, modules, alerts
- Health check endpoint
- Static file serving for the React dashboard
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from entropy.api.routers import alerts, modules, repos
from entropy.storage.db import init_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    logger.info("Entropy API starting up…")
    try:
        init_db()
        logger.info("Database initialized")
    except Exception:
        logger.warning("Database init failed — running in limited mode", exc_info=True)
    yield
    logger.info("Entropy API shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Entropy — Code Aging & Decay Tracker",
    description="API for analyzing and tracking software entropy across codebases.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# CORS for React dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(repos.router, prefix="/api", tags=["repos"])
app.include_router(modules.router, prefix="/api", tags=["modules"])
app.include_router(alerts.router, prefix="/api", tags=["alerts"])


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "entropy", "version": "1.0.0"}


# Serve React dashboard static files (if built)
dashboard_build = Path(__file__).parent.parent.parent / "dashboard" / "dist"
if dashboard_build.is_dir():
    app.mount("/", StaticFiles(directory=str(dashboard_build), html=True), name="dashboard")
