"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .config import settings
from .errors import AppError, app_error_handler, http_error_handler
from .http import close_http_client, get_http_client
from .routers import ai, chat, dashboard, food, goals, profile, weight, workouts

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_http_client()
    missing = [
        name
        for name, ok in (
            ("SUPABASE_URL/SUPABASE_ANON_KEY", settings.supabase_configured),
            ("GEMINI_API_KEY", settings.gemini_configured),
            ("UPSTASH_REDIS_REST_URL/TOKEN", settings.redis_configured),
        )
        if not ok
    ]
    if missing:
        log.warning("Starting with missing configuration: %s", ", ".join(missing))
    if settings.usda_api_key.upper() == "DEMO_KEY":
        log.warning("USDA_API_KEY is DEMO_KEY — fine for trying it out, rate limited in real use.")
    yield
    await close_http_client()


app = FastAPI(
    title="AI Nutrition & Fitness Tracker API",
    description=(
        "Backend for a personal nutrition and fitness tracker: manual logging, "
        "MET-based burn estimation, calorie-balance forecasting, Gemini photo "
        "recognition, generated summaries and a context-aware coach."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
app.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]

for module in (profile, goals, food, workouts, weight, dashboard, ai, chat):
    app.include_router(module.router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {"service": "fitness-tracker-api", "docs": "/docs", "health": "/health"}


@app.get("/health", tags=["meta"])
async def health() -> dict[str, Any]:
    """Unauthenticated liveness + configuration check (no secrets returned)."""
    return {
        "status": "ok",
        "env": settings.app_env,
        "integrations": {
            "supabase": settings.supabase_configured,
            "gemini": settings.gemini_configured,
            "gemini_model": settings.gemini_model if settings.gemini_configured else None,
            "usda": bool(settings.usda_api_key),
            "usda_demo_key": settings.usda_api_key.upper() == "DEMO_KEY",
            "redis": settings.redis_configured,
        },
    }
