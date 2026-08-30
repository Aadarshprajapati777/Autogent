"""Integration management. List connected integrations and kick off /
complete OAuth flows. Slack and GitHub are wired end-to-end here; other
providers (Jira, Linear, Notion, Google) follow the same pattern and will
be added in the same shape.
"""
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...config import settings
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.integrations import (
    Integration,
    IntegrationProvider,
    IntegrationState,
    OAuthCredential,
    OAuthState,
)
from ...services.credentials import vault
from ...services.slack import SlackClient

router = APIRouter(prefix="/integrations", tags=["integrations"])

OAUTH_EXPIRY = timedelta(minutes=10)

# Provider -> authorize URL + scopes + client id/secret from settings.
OAUTH_CONFIG: dict[str, dict] = {
    "slack": {
        "authorize_url": "https://slack.com/oauth/v2/authorize",
        "scopes": "chat:write im:write im:history users:read users:read.email",
        "client_id": settings.slack_client_id,
        "client_secret": settings.slack_client_secret,
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "scopes": "repo read:org",
        "client_id": settings.github_client_id,
        "client_secret": settings.github_client_secret,
    },
}


async def _require_admin(
    workspace_id: uuid.UUID, user: User, session: AsyncSession
) -> WorkspaceMember:
    member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not member or member.role.value not in ("owner", "admin"):
        raise HTTPException(403, "Workspace admin access required")
    return member


@router.get("")
async def list_integrations(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _require_admin(workspace_id, user, session)
    rows = (
        await session.execute(
            select(Integration).where(Integration.workspace_id == workspace_id)
        )
    ).scalars().all()
    return {
        "count": len(rows),
        "integrations": [
            {
                "id": str(i.id),
                "provider": i.provider.value,
                "state": i.state.value,
                "external_account_id": i.external_account_id,
                "last_synced_at": i.last_synced_at.isoformat() if i.last_synced_at else None,
            }
            for i in rows
        ],
    }


@router.get("/{provider}/connect")
async def oauth_connect(
    provider: str,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Start an OAuth flow: return the authorize URL the frontend should
    redirect the user to. We stash a one-time state token to bind the
    callback to this workspace + user."""
    await _require_admin(workspace_id, user, session)
    cfg = OAUTH_CONFIG.get(provider)
    if not cfg:
        raise HTTPException(404, f"Unknown provider: {provider}")
    if not cfg["client_id"]:
        raise HTTPException(400, f"{provider} OAuth is not configured on the server")

    state_token = secrets.token_urlsafe(32)
    # OAuth callbacks must hit the backend, not the frontend.
    redirect_uri = f"{settings.backend_url.rstrip('/')}/api/v1/integrations/{provider}/callback"
    state = OAuthState(
        provider=IntegrationProvider(provider),
        workspace_id=workspace_id,
        user_id=user.id,
        state=state_token,
        redirect_uri=redirect_uri,
        expires_at=datetime.now(UTC) + OAUTH_EXPIRY,
    )
    session.add(state)
    await session.commit()

    params = {
        "client_id": cfg["client_id"],
        "scope": cfg["scopes"],
        "state": state_token,
        "redirect_uri": redirect_uri,
    }
    return {"authorize_url": f"{cfg['authorize_url']}?{urlencode(params)}"}


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """OAuth callback. Exchange the code for an access token and store it
    encrypted, then redirect back to the frontend integrations page."""
    state_row = (
        await session.execute(
            select(OAuthState).where(OAuthState.state == state)
        )
    ).scalar_one_or_none()
    if not state_row or state_row.expires_at < datetime.now(UTC):
        raise HTTPException(400, "Invalid or expired OAuth state")
    if state_row.provider.value != provider:
        raise HTTPException(400, "Provider mismatch")

    cfg = OAUTH_CONFIG[provider]
    token = await _exchange_code(provider, cfg, code, state_row.redirect_uri)
    if not token:
        raise HTTPException(400, f"Failed to get {provider} access token")

    integration = (
        await session.execute(
            select(Integration).where(
                Integration.workspace_id == state_row.workspace_id,
                Integration.provider == state_row.provider,
            )
        )
    ).scalar_one_or_none()
    if integration:
        integration.state = IntegrationState.CONNECTED
    else:
        integration = Integration(
            workspace_id=state_row.workspace_id,
            provider=state_row.provider,
            state=IntegrationState.CONNECTED,
        )
        session.add(integration)
        await session.flush()

    # Replace any existing credential.
    existing_cred = (
        await session.execute(
            select(OAuthCredential).where(OAuthCredential.integration_id == integration.id)
        )
    ).scalar_one_or_none()
    if existing_cred:
        existing_cred.access_token_encrypted = vault.encrypt(token["access_token"])
    else:
        session.add(
            OAuthCredential(
                integration_id=integration.id,
                access_token_encrypted=vault.encrypt(token["access_token"]),
                scopes=token.get("scope", "").split() if token.get("scope") else [],
            )
        )

    await session.execute(OAuthState.__table__.delete().where(OAuthState.id == state_row.id))
    await session.commit()
    return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/integrations?connected={provider}")


async def _exchange_code(provider: str, cfg: dict, code: str, redirect_uri: str) -> dict | None:
    import httpx
    if provider == "slack":
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://slack.com/api/oauth.v2.access",
                data={
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                },
            )
            data = resp.json()
        if not data.get("ok"):
            return None
        return {"access_token": data["access_token"], "scope": data.get("scope", "")}
    if provider == "github":
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                },
                headers={"Accept": "application/json"},
            )
            data = resp.json()
        return {"access_token": data.get("access_token", ""), "scope": data.get("scope", "")}
    return None


@router.delete("/{provider}")
async def disconnect_integration(
    provider: str,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _require_admin(workspace_id, user, session)
    integration = (
        await session.execute(
            select(Integration).where(
                Integration.workspace_id == workspace_id,
                Integration.provider == IntegrationProvider(provider),
            )
        )
    ).scalar_one_or_none()
    if not integration:
        raise HTTPException(404, "Integration not found")
    integration.state = IntegrationState.DISCONNECTED
    await session.commit()
    return {"disconnected": True, "provider": provider}
