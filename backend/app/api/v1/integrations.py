"""Integration management. List connected integrations and kick off /
complete OAuth flows. Slack, GitHub, Jira, Linear, Notion, and Google
Calendar are OAuth-based. Recall.ai uses a backend API key (not per-
workspace OAuth) and is surfaced as a managed integration.
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

# Providers that use a backend-wide API key rather than per-workspace OAuth.
# These show as "connected" if the key is configured, with no Connect button.
BACKEND_CREDENTIAL_PROVIDERS: dict[str, callable] = {
    "recall": lambda: bool(settings.recall_api_key),
}

# Provider -> authorize URL + scopes + client id/secret from settings.
# Only providers with credentials configured are included.
OAUTH_CONFIG: dict[str, dict] = {
    "slack": {
        "authorize_url": "https://slack.com/oauth/v2/authorize",
        "scopes": "chat:write im:write im:history users:read users:read.email channels:read channels:join channels:history groups:history mpim:history",
        "client_id": settings.slack_client_id,
        "client_secret": settings.slack_client_secret,
        "token_url": "https://slack.com/api/oauth.v2.access",
        "token_style": "form",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "scopes": "repo read:org",
        "client_id": settings.github_client_id,
        "client_secret": settings.github_client_secret,
        "token_url": "https://github.com/login/oauth/access_token",
        "token_style": "json",
    },
    "jira": {
        "authorize_url": "https://auth.atlassian.com/authorize",
        "scopes": "read:jira-work read:jira-user write:jira-work offline_access",
        "client_id": settings.jira_client_id,
        "client_secret": settings.jira_client_secret,
        "token_url": "https://auth.atlassian.com/oauth/token",
        "token_style": "json",
        "extra_authorize_params": {
            "audience": "api.atlassian.com",
            "response_type": "code",
            "prompt": "consent",
        },
    },
    "linear": {
        "authorize_url": "https://linear.app/oauth/authorize",
        "scopes": "read,write",
        "client_id": settings.linear_client_id,
        "client_secret": settings.linear_client_secret,
        "token_url": "https://api.linear.app/oauth/token",
        "token_style": "form",
        "extra_authorize_params": {"prompt": "consent", "response_type": "code"},
    },
    "notion": {
        "authorize_url": "https://api.notion.com/v1/oauth/authorize",
        "scopes": "",  # Notion uses integration permissions, not scopes
        "client_id": settings.notion_client_id,
        "client_secret": settings.notion_client_secret,
        "token_url": "https://api.notion.com/v1/oauth/token",
        "token_style": "basic",
        "extra_authorize_params": {"owner": "user"},
    },
    "google_calendar": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "scopes": "https://www.googleapis.com/auth/calendar",
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "token_url": "https://oauth2.googleapis.com/token",
        "token_style": "json",
        "extra_authorize_params": {
            "access_type": "offline",
            "prompt": "consent",
            "response_type": "code",
        },
    },
}

# Filter to only providers that have credentials configured
OAUTH_CONFIG = {
    k: v for k, v in OAUTH_CONFIG.items() if v.get("client_id")
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
    result = [
        {
            "id": str(i.id),
            "provider": i.provider.value,
            "state": i.state.value,
            "external_account_id": i.external_account_id,
            "last_synced_at": i.last_synced_at.isoformat() if i.last_synced_at else None,
            "managed": False,
        }
        for i in rows
    ]
    # Add backend-credential providers (e.g. Recall.ai) as virtual entries
    existing_providers = {i.provider.value for i in rows}
    for provider, is_configured in BACKEND_CREDENTIAL_PROVIDERS.items():
        if provider not in existing_providers and is_configured():
            result.append({
                "id": None,
                "provider": provider,
                "state": "connected",
                "external_account_id": None,
                "last_synced_at": None,
                "managed": True,
            })
    return {"count": len(result), "integrations": result}


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
    if provider in BACKEND_CREDENTIAL_PROVIDERS:
        raise HTTPException(400, f"{provider} is a managed integration — no OAuth flow required")
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
        "state": state_token,
        "redirect_uri": redirect_uri,
    }
    if cfg.get("scopes"):
        params["scope"] = cfg["scopes"]
    # Merge in provider-specific params (e.g. audience for Jira, access_type for Google)
    params.update(cfg.get("extra_authorize_params", {}))
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
    now = datetime.now(UTC)
    expires = state_row.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if not state_row or expires < now:
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

    # After any integration connects, sync people from that integration
    # so the agent has a unified people graph. Fire-and-forget.
    import asyncio
    from ...services.people_sync import (
        sync_slack_members, sync_github_members,
        sync_jira_members, sync_linear_members,
    )
    sync_map = {
        "slack": sync_slack_members,
        "github": sync_github_members,
        "jira": sync_jira_members,
        "linear": sync_linear_members,
    }
    if provider in sync_map:
        asyncio.create_task(sync_map[provider](state_row.workspace_id))

    # For Slack, also send proactive onboarding DMs to new members
    if provider == "slack":
        from ...services.slack_onboarding import start_slack_onboarding
        asyncio.create_task(start_slack_onboarding(state_row.workspace_id, integration.id))

    return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/integrations?connected={provider}")


async def _exchange_code(provider: str, cfg: dict, code: str, redirect_uri: str) -> dict | None:
    import httpx
    token_url = cfg["token_url"]
    token_style = cfg.get("token_style", "json")

    async with httpx.AsyncClient(timeout=30.0) as client:
        if token_style == "form":
            # Form-encoded POST. Used by Slack (returns {ok: true, access_token})
            # and Linear (returns {access_token, ...}).
            resp = await client.post(
                token_url,
                data={
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()
            # Slack returns {ok: true/false}, Linear returns {access_token} directly
            if data.get("ok") is False:
                return None
            access_token = data.get("access_token", "")
            if not access_token:
                return None
            return {"access_token": access_token, "scope": data.get("scope", "")}

        if token_style == "basic":
            # Notion uses HTTP Basic auth with client_id:client_secret
            import base64
            creds = base64.b64encode(
                f"{cfg['client_id']}:{cfg['client_secret']}".encode()
            ).decode()
            resp = await client.post(
                token_url,
                json={
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/json",
                },
            )
            if resp.is_error:
                return None
            data = resp.json()
            return {"access_token": data.get("access_token", ""), "scope": ""}

        # Default: JSON body (GitHub, Jira/Atlassian, Linear, Google)
        body = {
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "authorization_code",
        }
        headers = {"Accept": "application/json"}
        # Jira/Atlassian requires client_id and client_secret in the body
        resp = await client.post(token_url, json=body, headers=headers)
        if resp.is_error:
            return None
        data = resp.json()
        access_token = data.get("access_token", "")
        if not access_token:
            return None
        return {"access_token": access_token, "scope": data.get("scope", "")}


@router.delete("/{provider}")
async def disconnect_integration(
    provider: str,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _require_admin(workspace_id, user, session)
    if provider in BACKEND_CREDENTIAL_PROVIDERS:
        raise HTTPException(400, f"{provider} is a managed integration and cannot be disconnected from the UI")
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


# ── Integration resource discovery & selection ──────────────────────────
# After connecting an integration, the user selects which repos (GitHub),
# projects (Jira/Linear), or channels (Slack) to track. These endpoints
# list available resources from the provider API and let the user pick
# which ones to monitor. The selections are stored in Integration.config.


async def _get_integration_token(
    session: AsyncSession, workspace_id: uuid.UUID, provider: str
) -> str | None:
    from ...services.integrations import get_integration_token
    from ...models.integrations import IntegrationProvider
    return await get_integration_token(
        session, workspace_id, IntegrationProvider(provider)
    )


@router.get("/{provider}/resources")
async def list_provider_resources(
    provider: str,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """List repos/projects/channels available from a connected integration.
    Returns resources the user can select to track."""
    await _require_admin(workspace_id, user, session)
    token = await _get_integration_token(session, workspace_id, provider)
    if not token:
        raise HTTPException(400, f"{provider} is not connected")

    import httpx

    if provider == "github":
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://api.github.com/user/repos",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                params={"per_page": 50, "sort": "updated"},
            )
            if resp.status_code >= 400:
                raise HTTPException(502, f"GitHub API error: {resp.text[:200]}")
            repos = resp.json()
            return {
                "provider": "github",
                "resources": [
                    {"id": str(r["id"]), "name": r["full_name"], "default_branch": r.get("default_branch", "main")}
                    for r in repos
                ],
            }

    if provider == "slack":
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://slack.com/api/conversations.list",
                headers={"Authorization": f"Bearer {token}"},
                data={"types": "public_channel", "limit": 100},
            )
            data = resp.json()
            if not data.get("ok"):
                raise HTTPException(502, f"Slack API error: {data.get('error', 'unknown')}")
            channels = [
                {"id": c["id"], "name": c["name"], "num_members": c.get("num_members", 0)}
                for c in data.get("channels", [])
            ]
            return {"provider": "slack", "resources": channels}

    if provider == "linear":
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": f"Bearer {token}"},
                json={"query": "{ teams { nodes { id name key } } }"},
            )
            if resp.status_code >= 400:
                raise HTTPException(502, f"Linear API error: {resp.text[:300]}")
            body = resp.json()
            if body.get("errors"):
                raise HTTPException(502, f"Linear API error: {str(body['errors'])[:300]}")
            data = body.get("data", {})
            teams = data.get("teams", {}).get("nodes", [])
            return {
                "provider": "linear",
                "resources": [
                    {"id": t["id"], "name": t["name"], "key": t.get("key", ""), "type": "team"}
                    for t in teams
                ],
            }

    if provider == "jira":
        # Jira Cloud: list accessible sites, then list projects from each
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            if resp.status_code >= 400:
                raise HTTPException(502, f"Jira API error: {resp.text[:200]}")
            sites = resp.json()
            resources = []
            for site in sites:
                cloud_id = site["id"]
                # Get projects from this site
                proj_resp = await client.get(
                    f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
                if proj_resp.status_code < 400:
                    projects = proj_resp.json()
                    for p in projects:
                        resources.append({
                            "id": p["id"],
                            "name": p["name"],
                            "key": p["key"],
                            "type": "project",
                            "site": site.get("url", ""),
                        })
            return {"provider": "jira", "resources": resources}

    raise HTTPException(400, f"Resource listing not supported for {provider}")


@router.put("/{provider}/config")
async def update_integration_config(
    provider: str,
    body: dict,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Save selected resources (repos, projects, channels) to the integration
    config so the agent knows which resources to track."""
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

    # Merge incoming config into existing config
    existing = integration.config or {}
    existing.update(body)
    integration.config = existing
    await session.commit()
    return {"saved": True, "provider": provider, "config": integration.config}


@router.get("/{provider}/config")
async def get_integration_config(
    provider: str,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get the current integration config (selected repos, projects, etc.)."""
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
    return {"provider": provider, "config": integration.config or {}}


@router.post("/sync")
async def sync_people(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Sync team members from all connected integrations. Pulls members from
    Slack, GitHub, Jira, and Linear, and creates/updates Person records with
    their integration-specific identities (slack_id, github_login,
    jira_account_id, linear_id). People are matched across integrations by
    email or name."""
    from ...services.people_sync import sync_all_integrations
    results = await sync_all_integrations(workspace_id)
    return {"synced": True, "results": results}


@router.post("/{provider}/sync")
async def sync_provider_people(
    provider: str,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Sync team members from a single integration."""
    from ...services.people_sync import (
        sync_slack_members, sync_github_members,
        sync_jira_members, sync_linear_members,
    )
    sync_map = {
        "slack": sync_slack_members,
        "github": sync_github_members,
        "jira": sync_jira_members,
        "linear": sync_linear_members,
    }
    if provider not in sync_map:
        raise HTTPException(400, f"Sync not supported for {provider}")
    result = await sync_map[provider](workspace_id)
    return result
