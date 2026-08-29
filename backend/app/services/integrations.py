"""Resolve integration credentials for a workspace. Tools call this to get
the decrypted OAuth token for a provider (Slack, GitHub, ...) instead of
querying the DB themselves.
"""
from __future__ import annotations

from sqlalchemy import select

from ..models.integrations import Integration, IntegrationProvider, IntegrationState, OAuthCredential
from .credentials import vault


async def get_integration_token(db, workspace_id, provider: IntegrationProvider) -> str | None:
    """Return the decrypted access token for a workspace's integration, or
    None if not connected."""
    integration = await db.scalar(
        select(Integration).where(
            Integration.workspace_id == workspace_id,
            Integration.provider == provider,
            Integration.state == IntegrationState.CONNECTED,
        )
    )
    if not integration:
        return None
    cred = await db.scalar(
        select(OAuthCredential).where(OAuthCredential.integration_id == integration.id)
    )
    if not cred:
        return None
    return vault.decrypt(cred.access_token_encrypted)


async def get_integration(db, workspace_id, provider: IntegrationProvider) -> Integration | None:
    return await db.scalar(
        select(Integration).where(
            Integration.workspace_id == workspace_id,
            Integration.provider == provider,
            Integration.state == IntegrationState.CONNECTED,
        )
    )
