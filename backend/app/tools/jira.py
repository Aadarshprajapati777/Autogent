"""Jira tools. The agent can list projects, view issues, and create issues.
Requires the Jira integration to be connected for the workspace.
"""
from __future__ import annotations

import httpx

from ..agent.registry import tool
from ..models.integrations import IntegrationProvider
from ..services.integrations import get_integration_token


async def _resolve_token(ctx) -> str | None:
    return await get_integration_token(ctx.db, ctx.workspace_id, IntegrationProvider.JIRA)


async def _get_first_site_id(token: str) -> str | None:
    """Get the first accessible Jira Cloud site ID."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            "https://api.atlassian.com/oauth/token/accessible-resources",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if resp.status_code >= 400:
            return None
        sites = resp.json()
        if not sites:
            return None
        return sites[0]["id"]


@tool(
    name="jira_list_projects",
    description="List Jira projects accessible to the connected integration.",
    parameters={"type": "object", "properties": {}},
)
async def jira_list_projects(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Jira is not connected for this workspace"}

    site_id = await _get_first_site_id(token)
    if not site_id:
        return {"error": "No accessible Jira sites"}

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"https://api.atlassian.com/ex/jira/{site_id}/rest/api/3/project",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if resp.status_code >= 400:
            return {"error": f"Jira {resp.status_code}: {resp.text[:200]}"}
        projects = resp.json()
        return {
            "count": len(projects),
            "projects": [
                {"id": p["id"], "key": p["key"], "name": p["name"]}
                for p in projects
            ],
        }


@tool(
    name="jira_list_issues",
    description="List recent issues from a Jira project. Use the project key (e.g. 'AUT').",
    parameters={
        "type": "object",
        "properties": {
            "project_key": {"type": "string", "description": "Jira project key, e.g. 'AUT'"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["project_key"],
    },
)
async def jira_list_issues(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Jira is not connected for this workspace"}

    site_id = await _get_first_site_id(token)
    if not site_id:
        return {"error": "No accessible Jira sites"}

    async with httpx.AsyncClient(timeout=20.0) as client:
        jql = f"project = {args['project_key']} ORDER BY updated DESC"
        # Jira deprecated GET /rest/api/3/search (410 Gone).
        # Use POST /rest/api/3/search/jql instead.
        resp = await client.post(
            f"https://api.atlassian.com/ex/jira/{site_id}/rest/api/3/search/jql",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "jql": jql,
                "fields": ["summary", "status", "assignee"],
                "maxResults": args.get("limit", 10),
            },
        )
        if resp.status_code >= 400:
            return {"error": f"Jira {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        issues = [
            {
                "key": i["key"],
                "summary": i["fields"]["summary"],
                "status": i["fields"]["status"]["name"],
                "assignee": i["fields"].get("assignee", {}).get("displayName") if i["fields"].get("assignee") else None,
            }
            for i in data.get("issues", [])
        ]
        return {"count": len(issues), "issues": issues}


@tool(
    name="jira_create_issue",
    description=(
        "Create an issue in a Jira project. Optionally assign it to a person "
        "by name — the tool looks up their Jira account ID from the people "
        "database. Use people_list or people_get first to find the person."
    ),
    parameters={
        "type": "object",
        "properties": {
            "project_key": {"type": "string", "description": "Jira project key"},
            "summary": {"type": "string", "description": "Issue title"},
            "description": {"type": "string"},
            "issue_type": {"type": "string", "default": "Task"},
            "assignee_name": {
                "type": "string",
                "description": "Name of the person to assign (must be synced from Jira)",
            },
        },
        "required": ["project_key", "summary"],
    },
)
async def jira_create_issue(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Jira is not connected for this workspace"}

    site_id = await _get_first_site_id(token)
    if not site_id:
        return {"error": "No accessible Jira sites"}

    # If assignee_name is given, look up their Jira account ID
    assignee_id = None
    if args.get("assignee_name"):
        from sqlalchemy import func, select
        from ..models.memory import Person
        person = await ctx.db.scalar(
            select(Person).where(
                Person.workspace_id == ctx.workspace_id,
                func.lower(Person.name) == args["assignee_name"].lower(),
            )
        )
        if not person:
            return {"error": f"Person '{args['assignee_name']}' not found. Use people_list to see available people."}
        if not person.jira_account_id:
            return {"error": f"'{person.name}' is not linked to a Jira account. Sync Jira members first."}
        assignee_id = person.jira_account_id

    async with httpx.AsyncClient(timeout=20.0) as client:
        fields = {
            "project": {"key": args["project_key"]},
            "summary": args["summary"],
            "description": args.get("description", ""),
            "issuetype": {"name": args.get("issue_type", "Task")},
        }
        if assignee_id:
            fields["assignee"] = {"accountId": assignee_id}

        resp = await client.post(
            f"https://api.atlassian.com/ex/jira/{site_id}/rest/api/3/issue",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            json={"fields": fields},
        )
        if resp.status_code >= 400:
            return {"error": f"Jira {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        return {"created": True, "key": data.get("key"), "assigned_to": args.get("assignee_name")}
