"""Agent chat endpoint. The frontend posts a user message here and gets back
the agent's answer plus the trace of tool calls it made. Conversation history
is persisted per workspace + user so each thread is continuous.
"""
import uuid
import time
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.loop import agent
from ...agent.registry import ToolContext
from ...api.deps import current_user
from ...db.session import get_session
from ...models.core import User
from ...models.pm_chat import PmChatMessage

router = APIRouter(prefix="/agent", tags=["agent"])

# Import the tools package so all tools register on first request.
import app.tools  # noqa: F401, E402

# Per-user agent rate limit: 20 messages / minute
_agent_rate: dict[uuid.UUID, list[float]] = {}
_AGENT_RATE_MAX = 20
_AGENT_RATE_WINDOW = 60.0


def _check_agent_rate(user_id: uuid.UUID) -> None:
    now = time.time()
    recent = [t for t in _agent_rate.get(user_id, []) if now - t < _AGENT_RATE_WINDOW]
    if len(recent) >= _AGENT_RATE_MAX:
        raise HTTPException(429, "Too many agent requests. Please slow down.")
    recent.append(now)
    _agent_rate[user_id] = recent


class AgentRequest(BaseModel):
    workspace_id: uuid.UUID
    message: str = Field(min_length=1, max_length=8000)


class AgentResponse(BaseModel):
    answer: str
    actions: list[dict] = []
    error: str | None = None


def _serialize(msg: PmChatMessage) -> dict:
    return {"role": msg.role, "text": msg.text, "actions": msg.actions or []}


def _to_llm_messages(history: list[PmChatMessage], user_message: str) -> list[dict]:
    """Convert persisted chat rows into the messages list the LLM expects.
    Assistant turns carry their tool calls; tool results are flattened into
    the assistant text for simplicity (the live trace is in `actions`)."""
    messages: list[dict] = []
    for row in history:
        if row.role == "user":
            messages.append({"role": "user", "content": row.text})
        else:
            content = row.text
            if row.actions:
                summary = "; ".join(
                    f"called {a.get('tool')}({a.get('arguments')})" for a in row.actions
                )
                content = f"{content}\n[actions: {summary}]" if content else f"[actions: {summary}]"
            messages.append({"role": "assistant", "content": content or ""})
    messages.append({"role": "user", "content": user_message})
    return messages


@router.post("/chat", response_model=AgentResponse)
async def agent_chat(
    body: AgentRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    _check_agent_rate(user.id)
    # Capture user_id up front — the session may expire the user object
    # during the agent loop (tool calls flush/rollback the session).
    user_id = user.id

    # Verify membership by loading the user's chat history in this workspace.
    history = (
        await session.execute(
            select(PmChatMessage)
            .where(
                PmChatMessage.workspace_id == body.workspace_id,
                PmChatMessage.user_id == user_id,
            )
            .order_by(PmChatMessage.created_at.asc())
            .limit(50)
        )
    ).scalars().all()

    # Persist the user's message.
    session.add(
        PmChatMessage(
            workspace_id=body.workspace_id,
            user_id=user_id,
            role="user",
            text=body.message,
        )
    )
    await session.flush()

    ctx = ToolContext(db=session, workspace_id=body.workspace_id, user_id=user_id)
    messages = _to_llm_messages(history, body.message)
    run = await agent.run(messages, ctx)

    # Persist the agent's reply + its action trace.
    session.add(
        PmChatMessage(
            workspace_id=body.workspace_id,
            user_id=user_id,
            role="assistant",
            text=run.answer,
            actions=run.actions(),
        )
    )
    await session.commit()

    return AgentResponse(answer=run.answer, actions=run.actions(), error=run.error)


@router.get("/history")
async def agent_history(
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = (
        await session.execute(
            select(PmChatMessage)
            .where(
                PmChatMessage.workspace_id == workspace_id,
                PmChatMessage.user_id == user.id,
            )
            .order_by(PmChatMessage.created_at.asc())
            .limit(100)
        )
    ).scalars().all()
    return {
        "count": len(rows),
        "messages": [
            {
                "role": r.role,
                "text": r.text,
                "actions": r.actions or [],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
