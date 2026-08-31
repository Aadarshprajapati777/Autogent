"""GitHub tools. The agent can list repos, view recent activity, and create
issues. Requires the GitHub integration to be connected for the workspace.
"""
from __future__ import annotations

import httpx

from ..agent.registry import tool
from ..models.integrations import IntegrationProvider
from ..services.integrations import get_integration_token

API = "https://api.github.com"


async def _gh(token: str, method: str, path: str, **kwargs) -> dict | list:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.request(
            method,
            f"{API}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            **kwargs,
        )
        if resp.status_code >= 400:
            return {"error": f"GitHub {resp.status_code}: {resp.text[:200]}"}
        return resp.json() if resp.content else {}


async def _resolve_token(ctx) -> str | None:
    return await get_integration_token(ctx.db, ctx.workspace_id, IntegrationProvider.GITHUB)


@tool(
    name="github_list_repos",
    description="List repositories the connected GitHub integration can see.",
    parameters={"type": "object", "properties": {"limit": {"type": "integer", "default": 30}}},
)
async def github_list_repos(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "GitHub is not connected for this workspace"}
    repos = await _gh(token, "GET", "/user/repos", params={"per_page": args.get("limit", 30), "sort": "updated"})
    if isinstance(repos, dict) and repos.get("error"):
        return repos
    return {
        "count": len(repos),
        "repos": [{"id": r["id"], "name": r["full_name"], "default_branch": r.get("default_branch")} for r in repos],
    }


@tool(
    name="github_recent_activity",
    description="List recent commits/activity for a repository.",
    parameters={
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "full name, e.g. 'owner/repo'"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["repo"],
    },
)
async def github_recent_activity(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "GitHub is not connected for this workspace"}
    commits = await _gh(
        token, "GET", f"/repos/{args['repo']}/commits",
        params={"per_page": args.get("limit", 10)},
    )
    if isinstance(commits, dict) and commits.get("error"):
        return commits
    return {
        "count": len(commits),
        "commits": [
            {
                "sha": c["sha"][:7],
                "message": c["commit"]["message"].splitlines()[0],
                "author": c["commit"]["author"]["name"],
                "date": c["commit"]["author"]["date"],
            }
            for c in commits
        ],
    }


@tool(
    name="github_create_issue",
    description=(
        "Open an issue in a repository. Optionally assign it to a person "
        "by name — the tool looks up their GitHub login from the people database."
    ),
    parameters={
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "full name, e.g. 'owner/repo'"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "assignee_name": {
                "type": "string",
                "description": "Name of the person to assign (must be synced from GitHub)",
            },
        },
        "required": ["repo", "title"],
    },
)
async def github_create_issue(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "GitHub is not connected for this workspace"}

    # If assignee_name is given, look up their GitHub login
    assignee_login = None
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
        if not person.github_login:
            return {"error": f"'{person.name}' is not linked to a GitHub account. Sync GitHub members first."}
        assignee_login = person.github_login

    payload = {"title": args["title"], "body": args.get("body", "")}
    if assignee_login:
        payload["assignees"] = [assignee_login]

    result = await _gh(
        token, "POST", f"/repos/{args['repo']}/issues",
        json=payload,
    )
    if isinstance(result, dict) and result.get("error"):
        return result
    return {"created": True, "number": result.get("number"), "url": result.get("html_url"), "assigned_to": args.get("assignee_name")}
