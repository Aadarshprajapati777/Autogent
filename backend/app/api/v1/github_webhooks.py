"""GitHub webhook receiver. Ingests push/PR events into GithubActivity rows
so the agent can reason about repo activity. Signature verification uses
HMAC-SHA256 with the GitHub webhook secret.
"""
import hashlib, hmac, json
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.session import SessionLocal
from ...models.integrations import GithubRepo, Integration, IntegrationProvider
from ...models.webhooks import WebhookEvent

router = APIRouter(prefix="/github/webhooks", tags=["github-webhooks"])


def _verify(payload: bytes, signature: str) -> bool:
    if not settings.github_webhook_secret:
        return True  # dev mode
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
) -> Response:
    body = await request.body()
    if not _verify(body, x_hub_signature_256 or ""):
        raise HTTPException(401, "Invalid GitHub webhook signature")
    payload = json.loads(body) if body else {}

    async with SessionLocal() as session:
        event = WebhookEvent(
            provider="github",
            event_id=x_github_delivery or "",
            event_type=x_github_event or "",
            payload=payload,
        )
        session.add(event)
        await session.commit()

    return Response(content="{}", media_type="application/json")
