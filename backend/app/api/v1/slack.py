"""Slack events endpoint. Slack sends user DMs and mentions here; we route
each message through the PM automation layer (onboarding, reply handling,
fact extraction) so the AI PM can respond and take action autonomously.
This is what makes Autogent reachable from Slack, not just the dashboard.
"""
import json
import logging
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.loop import agent
from ...agent.registry import ToolContext
from ...config import settings
from ...db.session import SessionLocal
from ...models.integrations import Integration, IntegrationProvider, IntegrationState
from ...services.pm_automation import process_slack_reply
from ...services.slack import verify_slack

log = logging.getLogger(__name__)
router = APIRouter(prefix="/slack", tags=["slack"])

import app.tools  # noqa: F401, E402

# Dedup: Slack retries events up to 3x. Track recent message IDs to avoid
# processing the same message twice.
_recent_event_ids: dict[str, float] = {}
_DEDUP_WINDOW = 300.0  # 5 minutes


async def _workspace_for_slack_team(session: AsyncSession, team_id: str) -> uuid.UUID | None:
    integration = (
        await session.execute(
            select(Integration).where(
                Integration.provider == IntegrationProvider.SLACK,
                Integration.state == IntegrationState.CONNECTED,
                Integration.external_account_id == team_id,
            )
        )
    ).scalar_one_or_none()
    return integration.workspace_id if integration else None


@router.post("/events")
async def slack_events(
    request: Request,
    x_slack_signature: str | None = Header(None),
    x_slack_request_timestamp: str | None = Header(None),
) -> Response:
    body = await request.body()
    # Signature verification (skipped in development if no signing secret)
    if settings.slack_signing_secret:
        try:
            verify_slack(
                {"x-slack-signature": x_slack_signature or "",
                 "x-slack-request-timestamp": x_slack_request_timestamp or ""},
                body,
            )
        except HTTPException:
            # In development, log but don't block — allows testing without
            # a configured signing secret.
            if settings.environment == "development":
                log.warning("Slack signature verification failed (dev mode, continuing)")
            else:
                raise

    payload = json.loads(body)

    # Slack URL verification challenge.
    if payload.get("type") == "url_verification":
        return Response(
            content=json.dumps({"challenge": payload.get("challenge", "")}),
            media_type="application/json",
        )

    event = payload.get("event", {})
    if event.get("type") != "message" or event.get("bot_id"):
        return Response(content="{}", media_type="application/json")

    # Dedup via Slack's event_id
    import time
    event_id = payload.get("event_id", "")
    if event_id:
        now = time.time()
        # Clean old entries
        stale = [k for k, t in _recent_event_ids.items() if now - t > _DEDUP_WINDOW]
        for k in stale:
            _recent_event_ids.pop(k, None)
        if event_id in _recent_event_ids:
            return Response(content="{}", media_type="application/json")
        _recent_event_ids[event_id] = now

    team_id = payload.get("team_id", "")
    text = event.get("text", "")
    channel = event.get("channel", "")
    user_id = event.get("user", "")
    thread_ts = event.get("thread_ts") or event.get("ts")

    async with SessionLocal() as session:
        workspace_id = await _workspace_for_slack_team(session, team_id)
        if not workspace_id:
            return Response(content="{}", media_type="application/json")

        # Route through PM automation: onboarding continuation or reply handling.
        # This handles fact extraction, state updates, and contextual responses.
        try:
            result = await process_slack_reply(
                session, user_id, text, thread_ts=thread_ts,
            )
            await session.commit()
        except Exception as exc:
            log.exception("PM automation failed for Slack event: %s", exc)
            await session.rollback()

            # Fallback: route through the generic agent loop so the user still
            # gets a response instead of silence.
            try:
                ctx = ToolContext(db=session, workspace_id=workspace_id)
                run = await agent.run(
                    [{"role": "user", "content": f"Slack message from {user_id}: {text}"}],
                    ctx,
                )
                await session.commit()
                if run.answer:
                    from ...services.integrations import get_integration_token
                    import httpx
                    token = await get_integration_token(session, workspace_id, IntegrationProvider.SLACK)
                    if token:
                        async with httpx.AsyncClient() as client:
                            await client.post(
                                "https://slack.com/api/chat.postMessage",
                                headers={"Authorization": f"Bearer {token}"},
                                json={"channel": channel, "text": run.answer, "thread_ts": thread_ts},
                            )
            except Exception:
                log.exception("Fallback agent also failed for Slack event")

    return Response(content="{}", media_type="application/json")
