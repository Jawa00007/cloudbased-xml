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
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Windows: psycopg needs SelectorEventLoop
import asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from backend.api.auth import set_admin_credentials
from backend.api.routes.accounts import router as accounts_router
from backend.api.routes.admin import router as admin_router
from backend.api.routes.aggregation import router as aggregation_router
from backend.api.routes.auth import router as auth_router
from backend.api.routes.files import router as files_router
from backend.api.routes.forecast import router as forecast_router
from backend.api.routes.measurements import router as measurements_router
from backend.api.routes.monitoring import router as monitoring_router
from backend.api.routes.sync import router as sync_router
from backend.api.routes.users import router as users_router
from backend.core.config import settings
from backend.db.session import get_public_session
from backend.forecast.loss_calculator import DEFAULT_RULES
from backend.ingestion.lock import guard
from backend.scheduler.jobs import scheduler, start_scheduler, stop_scheduler

# Custom Prometheus gauges — updated on every /api/health call
_db_health_gauge   = Gauge("sii_db_health",        "DB reachable: 1=ok 0=error")
_ingestion_running = Gauge("sii_ingestion_running", "Ingestion guard: 1=running 0=idle")

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

    # Seed default loss config rules if the table is empty
    try:
        async with get_public_session() as session:
            from sqlalchemy import text as _text
            count = (await session.execute(_text("SELECT COUNT(*) FROM loss_config"))).scalar()
            if count == 0:
                _SEED = [
                    ("Missing POD (high voltage fallback)", "missing_pod",    None,       0.10,  1),
                    ("High voltage 220/380V",               "tensione_range", "220,380",  0.10,  2),
                    ("MT tariff",                           "tariffa_prefix", "MT",       0.038, 3),
                    ("Default (all others)",                "default",        None,       0.018, 99),
                ]
                for name, ct, cv, lp, pr in _SEED:
                    await session.execute(_text("""
                        INSERT INTO loss_config (name, condition_type, condition_value, loss_pct, priority)
                        VALUES (:name, :ct, :cv, :lp, :pr)
                        ON CONFLICT DO NOTHING
                    """), {"name": name, "ct": ct, "cv": cv, "lp": lp, "pr": pr})
                logger.info("Seeded %d default loss config rules", len(_SEED))
    except Exception as exc:
        logger.warning("Could not seed loss_config (table may not exist yet): %s", exc)

    # Guard: refuse to start production with dev placeholder credentials
    if settings.ENVIRONMENT == "production":
        if "dev-" in settings.SECRET_KEY or "dev-" in settings.API_KEY:
            raise RuntimeError(
                "Production started with dev placeholder credentials. "
                "Set SECRET_KEY and API_KEY to strong values in .env before deploying."
            )

    # Start nightly scheduler (only in production / staging)
    if settings.ENVIRONMENT != "development":
        start_scheduler()

    yield

    stop_scheduler()


# ── App ────────────────────────────────────────────────────────────────────────

_in_production = settings.ENVIRONMENT == "production"

app = FastAPI(
    title="SII Energy Measurement Analytics",
    description="REST API for Italian SII electricity measurement data",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if _in_production else "/docs",
    redoc_url=None if _in_production else "/redoc",
)

# CORS — controlled via ALLOWED_ORIGINS env var (comma-separated list or *)
# allow_credentials must be False when using wildcard origin (browser requirement)
_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# Prometheus instrumentation — must be registered before routers so middleware
# wraps all requests. Exposes /api/metrics (blocked externally by nginx).
Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")

# ── Routers — all mounted under /api so nginx can route cleanly ────────────────
# Frontend is served at / by nginx; API lives at /api/*

_API = "/api"

app.include_router(auth_router,        prefix=_API)
app.include_router(accounts_router,    prefix=_API)
app.include_router(measurements_router, prefix=_API)
app.include_router(aggregation_router, prefix=_API)
app.include_router(files_router,       prefix=_API)
app.include_router(sync_router,        prefix=_API)
app.include_router(monitoring_router,  prefix=_API)
app.include_router(admin_router,       prefix=_API)
app.include_router(users_router,       prefix=_API)
app.include_router(forecast_router,    prefix=_API)


@app.get("/api/health", tags=["system"])
async def health() -> dict:
    """
    Deep health check — always returns HTTP 200.
    status="degraded" in the body signals DB unreachable; uptime monitors use HTTP code only.
    Also updates Prometheus gauges so Grafana dashboards reflect live state.
    """
    db_status = "ok"
    db_latency_ms = None
    try:
        t = time.monotonic()
        async with get_public_session() as s:
            await asyncio.wait_for(s.execute(text("SELECT 1")), timeout=2.0)
        db_latency_ms = round((time.monotonic() - t) * 1000, 1)
    except Exception:
        db_status = "error"

    _db_health_gauge.set(1 if db_status == "ok" else 0)
    _ingestion_running.set(1 if guard.is_running() else 0)

    next_run = None
    job = scheduler.get_job("nightly_ingest")
    if job and job.next_run_time:
        next_run = job.next_run_time.isoformat()

    body = {
        "status": "ok" if db_status == "ok" else "degraded",
        "environment": settings.ENVIRONMENT,
        "database": {"status": db_status, "latency_ms": db_latency_ms},
        "scheduler": {"running": scheduler.running, "next_run": next_run},
        "ingestion": {
            "running": guard.is_running(),
            "triggered_by": guard.triggered_by,
            "current_account": guard.current_account,
        },
    }
    if db_status != "ok":
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=503, content=body)
    return body
