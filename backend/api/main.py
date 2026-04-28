"""
SII Energy Measurement Analytics Platform — FastAPI application.

Auth:
  POST /auth/token           — issue JWT (username + password)
  All other endpoints        — X-API-Key header OR Bearer JWT

Run:
  uvicorn backend.api.main:app --reload --port 8000
"""

from __future__ import annotations

import hashlib
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Windows: psycopg needs SelectorEventLoop
import asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.auth import set_admin_credentials
from backend.api.routes.accounts import router as accounts_router
from backend.api.routes.aggregation import router as aggregation_router
from backend.api.routes.auth import router as auth_router
from backend.api.routes.files import router as files_router
from backend.api.routes.measurements import router as measurements_router
from backend.api.routes.monitoring import router as monitoring_router
from backend.api.routes.sync import router as sync_router
from backend.core.config import settings
from backend.scheduler.jobs import start_scheduler, stop_scheduler

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register admin credentials from environment
    admin_user = getattr(settings, "ADMIN_USERNAME", "admin")
    admin_pass = getattr(settings, "ADMIN_PASSWORD", "")
    if admin_pass:
        set_admin_credentials(admin_user, hashlib.sha256(admin_pass.encode()).hexdigest())
        logger.info("Admin user %r registered", admin_user)
    else:
        logger.warning("ADMIN_PASSWORD not set — JWT login disabled (API key still works)")

    # Start nightly scheduler (only in production / staging)
    if settings.ENVIRONMENT != "development":
        start_scheduler()

    yield

    stop_scheduler()


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="SII Energy Measurement Analytics",
    description="REST API for Italian SII electricity measurement data",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — controlled via ALLOWED_ORIGINS env var (comma-separated list or *)
_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(measurements_router)
app.include_router(aggregation_router)
app.include_router(files_router)
app.include_router(sync_router)
app.include_router(monitoring_router)


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "environment": settings.ENVIRONMENT}
