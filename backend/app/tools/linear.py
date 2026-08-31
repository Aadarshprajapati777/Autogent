"""Linear tools. The agent can list projects, view issues, and create issues.
Requires the Linear integration to be connected for the workspace.
"""
from __future__ import annotations

import httpx

from ..agent.registry import tool
from ..models.integrations import IntegrationProvider
from ..services.integrations import get_integration_token


async def _resolve_token(ctx) -> str | None:
    return await get_integration_token(ctx.db, ctx.workspace_id, IntegrationProvider.LINEAR)


async def _linear_query(token: str, query: str, variables: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.linear.app/graphql",
            headers={"Authorization": f"Bearer {token}"},
            json={"query": query, "variables": variables or {}},
        )
        if resp.status_code >= 400:
            return {"error": f"Linear {resp.status_code}: {resp.text[:200]}"}
        body = resp.json()
        if body.get("errors"):
            return {"error": str(body["errors"][:1])}
        return body.get("data", {})


@tool(
    name="linear_list_teams",
    description="List Linear teams accessible to the connected integration.",
    parameters={"type": "object", "properties": {}},
)
async def linear_list_teams(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Linear is not connected for this workspace"}
    data = await _linear_query(token, "{ teams { nodes { id name key } } }")
    if "error" in data:
        return data
    teams = data.get("teams", {}).get("nodes", [])
    return {
        "count": len(teams),
        "teams": [{"id": t["id"], "name": t["name"], "key": t.get("key", "")} for t in teams],
    }


@tool(
    name="linear_list_issues",
    description="List recent issues from a Linear team. Use the team key (e.g. 'ENG').",
    parameters={
        "type": "object",
        "properties": {
            "team_key": {"type": "string", "description": "Linear team key, e.g. 'ENG'"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["team_key"],
    },
)
async def linear_list_issues(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Linear is not connected for this workspace"}
    # Linear's Query.team uses `id`, not `key`. Use the team filter on the
    # issues connection instead: filter: { team: { key: { eq: $teamKey } } }
    query = """
    query($teamKey: String!, $limit: Int!) {
      issues(
        filter: { team: { key: { eq: $teamKey } } }
        first: $limit
        orderBy: updatedAt
      ) {
        nodes {
          id
          identifier
          title
          state { name }
          assignee { name }
          team { key name }
        }
      }
    }
    """
    data = await _linear_query(token, query, {"teamKey": args["team_key"], "limit": args.get("limit", 10)})
    if "error" in data:
        return data
    issues = data.get("issues", {}).get("nodes", [])
    return {
        "count": len(issues),
        "issues": [
            {
                "id": i["identifier"],
                "title": i["title"],
                "status": i["state"]["name"] if i.get("state") else None,
                "assignee": i["assignee"]["name"] if i.get("assignee") else None,
            }
            for i in issues
        ],
    }


@tool(
    name="linear_create_issue",
    description=(
        "Create an issue in a Linear team. Optionally assign it to a person "
        "by name — the tool looks up their Linear ID from the people database."
    ),
    parameters={
        "type": "object",
        "properties": {
            "team_key": {"type": "string", "description": "Linear team key"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "assignee_name": {
                "type": "string",
                "description": "Name of the person to assign (must be synced from Linear)",
            },
        },
        "required": ["team_key", "title"],
    },
)
async def linear_create_issue(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Linear is not connected for this workspace"}

    # If assignee_name is given, look up their Linear ID
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
        if not person.linear_id:
            return {"error": f"'{person.name}' is not linked to a Linear account. Sync Linear members first."}
        assignee_id = person.linear_id

    input_fields = {
        "teamKey": args["team_key"],
        "title": args["title"],
        "description": args.get("description", ""),
    }
    if assignee_id:
        input_fields["assigneeId"] = assignee_id

    query = """
    mutation($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue { id identifier url }
      }
    }
    """
    data = await _linear_query(token, query, {"input": input_fields})
    if "error" in data:
        return data
    result = data.get("issueCreate", {})
    issue = result.get("issue", {})
    return {
        "created": result.get("success", False),
        "id": issue.get("identifier"),
        "url": issue.get("url"),
    }
