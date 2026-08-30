from contextlib import asynccontextmanager
import asyncio
import logging
import sys

# psycopg3 needs the SelectorEventLoop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text as sql_text

from .config import settings
from .api.middleware import (
    BodySizeLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
    configure_logging,
)
from .api.v1.agent import router as agent_router
from .api.v1.approvals import router as approval_router
from .api.v1.auth import router as auth_router
from .api.v1.github_webhooks import router as github_webhooks_router
from .api.v1.integrations import router as integration_router
from .api.v1.meetings import router as meeting_router
from .api.v1.members import router as members_router
from .api.v1.memory import router as memory_router
from .api.v1.payments import router as payments_router
from .api.v1.recall_webhooks import router as recall_webhooks_router
from .api.v1.reports import router as reports_router
from .api.v1.settings import router as settings_router
from .api.v1.slack import router as slack_router
from .api.v1.tasks import router as tasks_router
from .api.v1.workspaces import router as workspace_router
from .db.base import Base
from .db.session import engine

log = logging.getLogger("autogent.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("startup environment=%s backend_url=%s", settings.environment, settings.backend_url)

    # Schema: use Alembic migrations in production; create_all only in dev.
    if settings.is_production:
        log.info("production mode — skipping create_all; ensure migrations are applied")
    else:
        async with engine.begin() as conn:
            import app.models  # noqa: F401
            await conn.run_sync(Base.metadata.create_all)

    # Start the proactive agent scheduler — runs check-in cycles so the
    # agent acts without a user prompt.
    from .services.pm_scheduler import start_scheduler, stop_scheduler
    await start_scheduler()
    try:
        yield
    finally:
        log.info("shutdown: stopping scheduler and disposing engine")
        await stop_scheduler()
        await engine.dispose()


app = FastAPI(title="Autogent API", version="0.1.0", lifespan=lifespan)

# Middleware order matters: outermost first.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(RequestIdMiddleware)

# CORS — strict in production, permissive in dev
_allowed_origins = (
    [settings.frontend_url]
    if settings.is_production
    else ["http://localhost:3000", "http://127.0.0.1:3000", settings.frontend_url]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
)


# ── Global exception handlers ──


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
                "request_id": rid,
            }
        },
        headers={"X-Request-Id": rid} if rid else None,
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    rid = getattr(request.state, "request_id", None)
    log.exception("unhandled exception request_id=%s path=%s", rid, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Internal server error",
                "request_id": rid,
            }
        },
        headers={"X-Request-Id": rid} if rid else None,
    )


# ── Health / readiness ──


@app.get("/health")
async def health() -> dict:
    """Liveness probe — process is up."""
    return {"status": "ok", "service": "autogent-api", "environment": settings.environment}


@app.get("/ready")
async def readiness() -> dict:
    """Readiness probe — can serve traffic (DB reachable)."""
    checks: dict[str, str] = {}
    overall = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(sql_text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"fail: {exc.__class__.__name__}"
        overall = "fail"
    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content={"status": overall, "checks": checks},
    )


# ── Routers ──
app.include_router(auth_router, prefix="/api/v1")
app.include_router(workspace_router, prefix="/api/v1")
app.include_router(integration_router, prefix="/api/v1")
app.include_router(memory_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(slack_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(approval_router, prefix="/api/v1")
app.include_router(meeting_router, prefix="/api/v1")
app.include_router(members_router, prefix="/api/v1")
app.include_router(payments_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(github_webhooks_router, prefix="/api/v1")
app.include_router(recall_webhooks_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
