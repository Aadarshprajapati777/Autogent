"""Unified people sync service. Pulls team members from connected integrations
(Slack, GitHub, Jira, Linear) and creates/updates Person records with their
integration-specific identities. People are matched across integrations using
email (primary key) or name (fallback).

This is what makes the agent able to:
- Know that "Sudhir" on Slack is "sudhirsahace" on GitHub
- Assign a Jira ticket to the right person by looking up their jira_account_id
- Send a Slack check-in to the GitHub user who just pushed code
- Build a unified profile from multiple sources

Each sync function:
1. Fetches members from the integration API
2. For each member, tries to match an existing Person by email → slack_id →
   github_login → jira_account_id → linear_id → name
3. If no match, creates a new Person
4. Updates the integration-specific fields on the matched/created Person
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import func, select

from ..db.session import SessionLocal
from ..models.integrations import IntegrationProvider
from ..models.memory import Person, PersonRole
from .integrations import get_integration_token

log = logging.getLogger(__name__)


# ── Matching logic ──────────────────────────────────────────────────────

async def _find_or_create_person(
    session,
    workspace_id: uuid.UUID,
    *,
    email: str | None = None,
    name: str | None = None,
    slack_id: str | None = None,
    github_login: str | None = None,
    github_id: str | None = None,
    jira_account_id: str | None = None,
    linear_id: str | None = None,
) -> tuple[Person, bool]:
    """Find an existing Person by any linked identity, or create a new one.
    Returns (person, created)."""
    # Try matching by integration-specific IDs first (most reliable)
    conditions = []
    if slack_id:
        conditions.append(Person.slack_id == slack_id)
    if github_id:
        conditions.append(Person.github_id == github_id)
    if github_login:
        conditions.append(func.lower(Person.github_login) == github_login.lower())
    if jira_account_id:
        conditions.append(Person.jira_account_id == jira_account_id)
    if linear_id:
        conditions.append(Person.linear_id == linear_id)
    if email:
        conditions.append(func.lower(Person.email) == email.lower())

    for cond in conditions:
        person = await session.scalar(
            select(Person).where(
                Person.workspace_id == workspace_id,
                cond,
            )
        )
        if person:
            return person, False

    # Fallback: match by name (case-insensitive)
    if name:
        person = await session.scalar(
            select(Person).where(
                Person.workspace_id == workspace_id,
                func.lower(Person.name) == name.lower(),
            )
        )
        if person:
            return person, False

    # No match — create new person
    person = Person(
        workspace_id=workspace_id,
        name=name or email or "Unknown",
        role=PersonRole.OTHER,
        email=email,
        slack_id=slack_id,
        github_login=github_login,
        github_id=github_id,
        jira_account_id=jira_account_id,
        linear_id=linear_id,
        onboarding_completed=False,
    )
    session.add(person)
    await session.flush()
    return person, True


def _merge_field(person: Person, field: str, value: Any) -> None:
    """Set a field on person only if the current value is empty and the new
    value is non-empty. Preserves existing data."""
    if value and not getattr(person, field, None):
        setattr(person, field, value)


# ── Slack sync ──────────────────────────────────────────────────────────

async def sync_slack_members(workspace_id: uuid.UUID) -> dict:
    """Pull all Slack workspace members and create/update Person records."""
    async with SessionLocal() as session:
        token = await get_integration_token(session, workspace_id, IntegrationProvider.SLACK)
        if not token:
            return {"error": "Slack not connected", "synced": 0}

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://slack.com/api/users.list",
                headers={"Authorization": f"Bearer {token}"},
            )
            data = resp.json()
            if not data.get("ok"):
                return {"error": f"Slack API: {data.get('error')}", "synced": 0}

            members = [
                m for m in data.get("members", [])
                if not m.get("is_bot") and not m.get("deleted") and m.get("id") != "USLACKBOT"
            ]

            created = 0
            updated = 0
            for m in members:
                profile = m.get("profile", {})
                real_name = profile.get("real_name") or m.get("name", "Unknown")
                email = profile.get("email")
                avatar = profile.get("image_72") or profile.get("image_48")

                person, was_created = await _find_or_create_person(
                    session, workspace_id,
                    email=email,
                    name=real_name,
                    slack_id=m["id"],
                )
                # Always update Slack-specific fields
                person.slack_id = m["id"]
                person.slack_handle = m.get("name")
                _merge_field(person, "email", email)
                _merge_field(person, "avatar_url", avatar)
                _merge_field(person, "timezone", m.get("tz"))

                if was_created:
                    created += 1
                else:
                    updated += 1

            await session.commit()
            log.info("Slack sync for %s: %d created, %d updated", workspace_id, created, updated)
            return {"provider": "slack", "total": len(members), "created": created, "updated": updated}


# ── GitHub sync ─────────────────────────────────────────────────────────

async def sync_github_members(workspace_id: uuid.UUID) -> dict:
    """Pull GitHub collaborators from tracked repos and create/update Person
    records with their GitHub identity."""
    async with SessionLocal() as session:
        token = await get_integration_token(session, workspace_id, IntegrationProvider.GITHUB)
        if not token:
            return {"error": "GitHub not connected", "synced": 0}

        # Get tracked repos from integration config
        from ..models.integrations import Integration
        integration = await session.scalar(
            select(Integration).where(
                Integration.workspace_id == workspace_id,
                Integration.provider == IntegrationProvider.GITHUB,
            )
        )
        if not integration:
            return {"error": "GitHub integration not found", "synced": 0}

        config = integration.config or {}
        # If no repos selected, try to list all repos and sync collaborators
        repos_to_sync = []

        async with httpx.AsyncClient(timeout=20.0) as client:
            if config.get("selected_resources"):
                # Fetch repo names for selected IDs
                resp = await client.get(
                    "https://api.github.com/user/repos",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    params={"per_page": 100, "sort": "updated"},
                )
                if resp.status_code < 400:
                    all_repos = resp.json()
                    selected_ids = set(str(r) for r in config["selected_resources"])
                    repos_to_sync = [
                        r["full_name"] for r in all_repos
                        if str(r["id"]) in selected_ids
                    ]
            else:
                # No repos selected — sync from recently updated repos
                resp = await client.get(
                    "https://api.github.com/user/repos",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    params={"per_page": 20, "sort": "updated"},
                )
                if resp.status_code < 400:
                    repos_to_sync = [r["full_name"] for r in resp.json()[:10]]

            if not repos_to_sync:
                return {"error": "No repos to sync", "synced": 0}

            seen_logins: set[str] = set()
            created = 0
            updated = 0

            for repo in repos_to_sync:
                # Get collaborators
                resp = await client.get(
                    f"https://api.github.com/repos/{repo}/collaborators",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    params={"per_page": 50},
                )
                if resp.status_code >= 400:
                    continue
                collaborators = resp.json()

                for c in collaborators:
                    login = c["login"]
                    if login in seen_logins:
                        continue
                    seen_logins.add(login)

                    # Fetch full user profile for email and name
                    user_resp = await client.get(
                        f"https://api.github.com/users/{login}",
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    )
                    if user_resp.status_code >= 400:
                        continue
                    user = user_resp.json()

                    name = user.get("name") or login
                    email = user.get("email")  # GitHub hides email unless public
                    github_id = str(user.get("id", ""))

                    person, was_created = await _find_or_create_person(
                        session, workspace_id,
                        email=email,
                        name=name,
                        github_login=login,
                        github_id=github_id,
                    )
                    person.github_login = login
                    person.github_id = github_id
                    _merge_field(person, "email", email)
                    _merge_field(person, "avatar_url", user.get("avatar_url"))
                    # If GitHub says they're a hireable developer, mark technical
                    if user.get("hireable"):
                        person.is_technical = True

                    if was_created:
                        created += 1
                    else:
                        updated += 1

            await session.commit()
            log.info("GitHub sync for %s: %d created, %d updated", workspace_id, created, updated)
            return {
                "provider": "github",
                "repos_scanned": len(repos_to_sync),
                "total": len(seen_logins),
                "created": created,
                "updated": updated,
            }


# ── Jira sync ───────────────────────────────────────────────────────────

async def sync_jira_members(workspace_id: uuid.UUID) -> dict:
    """Pull assignable Jira users and create/update Person records with their
    Jira account ID — needed for assigning issues."""
    async with SessionLocal() as session:
        token = await get_integration_token(session, workspace_id, IntegrationProvider.JIRA)
        if not token:
            return {"error": "Jira not connected", "synced": 0}

        async with httpx.AsyncClient(timeout=20.0) as client:
            # Get accessible sites
            resp = await client.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            if resp.status_code >= 400:
                return {"error": f"Jira API: {resp.text[:200]}", "synced": 0}
            sites = resp.json()
            if not sites:
                return {"error": "No Jira sites", "synced": 0}

            created = 0
            updated = 0
            total = 0

            for site in sites:
                cloud_id = site["id"]
                # Get assignable users (requires read:jira-user scope)
                resp = await client.get(
                    f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/users/search",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
                if resp.status_code >= 400:
                    continue
                users = resp.json()

                for u in users:
                    if u.get("accountType") == "app":
                        continue  # Skip bot accounts
                    account_id = u.get("accountId", "")
                    display_name = u.get("displayName", "Unknown")
                    email = u.get("emailAddress")
                    avatar = u.get("avatarUrls", {}).get("48x48")

                    if not account_id:
                        continue
                    total += 1

                    person, was_created = await _find_or_create_person(
                        session, workspace_id,
                        email=email,
                        name=display_name,
                        jira_account_id=account_id,
                    )
                    person.jira_account_id = account_id
                    person.jira_display_name = display_name
                    _merge_field(person, "email", email)
                    _merge_field(person, "avatar_url", avatar)

                    if was_created:
                        created += 1
                    else:
                        updated += 1

            await session.commit()
            log.info("Jira sync for %s: %d created, %d updated", workspace_id, created, updated)
            return {
                "provider": "jira",
                "sites_scanned": len(sites),
                "total": total,
                "created": created,
                "updated": updated,
            }


# ── Linear sync ─────────────────────────────────────────────────────────

async def sync_linear_members(workspace_id: uuid.UUID) -> dict:
    """Pull Linear team members and create/update Person records."""
    async with SessionLocal() as session:
        token = await get_integration_token(session, workspace_id, IntegrationProvider.LINEAR)
        if not token:
            return {"error": "Linear not connected", "synced": 0}

        async with httpx.AsyncClient(timeout=20.0) as client:
            # Linear GraphQL — fetch all users across teams
            resp = await client.post(
                "https://api.linear.app/graphql",
                headers={"Authorization": f"Bearer {token}"},
                json={"query": "{ users { nodes { id name email avatarUrl } } }"},
            )
            if resp.status_code >= 400:
                return {"error": f"Linear API: {resp.text[:200]}", "synced": 0}
            body = resp.json()
            if body.get("errors"):
                return {"error": f"Linear GraphQL: {str(body['errors'])[:200]}", "synced": 0}

            users = body.get("data", {}).get("users", {}).get("nodes", [])
            created = 0
            updated = 0

            for u in users:
                linear_id = u.get("id", "")
                name = u.get("name", "Unknown")
                email = u.get("email")
                avatar = u.get("avatarUrl")

                if not linear_id:
                    continue

                person, was_created = await _find_or_create_person(
                    session, workspace_id,
                    email=email,
                    name=name,
                    linear_id=linear_id,
                )
                person.linear_id = linear_id
                _merge_field(person, "email", email)
                _merge_field(person, "avatar_url", avatar)

                if was_created:
                    created += 1
                else:
                    updated += 1

            await session.commit()
            log.info("Linear sync for %s: %d created, %d updated", workspace_id, created, updated)
            return {
                "provider": "linear",
                "total": len(users),
                "created": created,
                "updated": updated,
            }


# ── Unified sync ────────────────────────────────────────────────────────

async def sync_all_integrations(workspace_id: uuid.UUID) -> dict:
    """Sync people from all connected integrations. Called after any
    integration is connected, or on-demand via API."""
    results = {}
    for provider, sync_fn in [
        ("slack", sync_slack_members),
        ("github", sync_github_members),
        ("jira", sync_jira_members),
        ("linear", sync_linear_members),
    ]:
        try:
            result = await sync_fn(workspace_id)
            results[provider] = result
        except Exception as e:
            log.warning("Failed to sync %s for %s: %s", provider, workspace_id, e)
            results[provider] = {"error": str(e)}
    return results
