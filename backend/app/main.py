from contextlib import asynccontextmanager
import asyncio
import sys

# psycopg3 needs the SelectorEventLoop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
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


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        await stop_scheduler()
        await engine.dispose()


app = FastAPI(title="Autogent API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        settings.frontend_url,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "autogent-api"}


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
