"""Slack events endpoint. Slack sends user DMs and mentions here; we route
each message to the agent so it can respond and take action. This is what
makes Autogent reachable from Slack, not just the dashboard.
"""
import json
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.loop import agent
from ...agent.registry import ToolContext
from ...config import settings
from ...db.session import SessionLocal
from ...models.integrations import Integration, IntegrationProvider, IntegrationState
from ...services.slack import verify_slack

router = APIRouter(prefix="/slack", tags=["slack"])

import app.tools  # noqa: F401, E402


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
    verify_slack(
        {"x-slack-signature": x_slack_signature or "", "x-slack-request-timestamp": x_slack_request_timestamp or ""},
        body,
    )
    payload = json.loads(body)

    # Slack URL verification challenge.
    if payload.get("type") == "url_verification":
        return Response(content=json.dumps({"challenge": payload.get("challenge", "")}), media_type="application/json")

    event = payload.get("event", {})
    if event.get("type") != "message" or event.get("bot_id"):
        return Response(content="{}", media_type="application/json")

    team_id = payload.get("team_id", "")
    text = event.get("text", "")
    channel = event.get("channel", "")
    user_id = event.get("user", "")

    async with SessionLocal() as session:
        workspace_id = await _workspace_for_slack_team(session, team_id)
        if not workspace_id:
            return Response(content="{}", media_type="application/json")

        ctx = ToolContext(db=session, workspace_id=workspace_id)
        run = await agent.run(
            [{"role": "user", "content": f"Slack message from {user_id} in {channel}: {text}"}],
            ctx,
        )
        await session.commit()

        # Reply in the same channel if the agent produced an answer.
        if run.answer:
            from ...services.integrations import get_integration_token
            import httpx
            token = await get_integration_token(session, workspace_id, IntegrationProvider.SLACK)
            if token:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://slack.com/api/chat.postMessage",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"channel": channel, "text": run.answer},
                    )

    return Response(content="{}", media_type="application/json")
