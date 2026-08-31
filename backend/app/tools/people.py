"""People & profile tools. The agent builds rich profiles automatically:
every time it learns something about a person (from a meeting, Slack, or
direct input) it upserts the Person row and links facts. Reliability is
derived from commitment vs. completed facts.
"""
from __future__ import annotations

from sqlalchemy import func, select

from ..agent.registry import tool
from ..models.memory import (
    Fact,
    FactKind,
    Person,
    PersonRole,
    Project,
    TemporalStatus,
)


@tool(
    name="people_upsert",
    description=(
        "Create or update a person's profile. Use this when you learn about "
        "someone new, or when you discover updated skills, role, availability, "
        "or goals. Auto-profile creation: call this whenever a person is "
        "mentioned and doesn't yet exist in memory."
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "role": {
                "type": "string",
                "enum": [r.value for r in PersonRole],
                "default": "other",
            },
            "title": {"type": "string"},
            "skills": {"type": "array", "items": {"type": "string"}},
            "languages": {"type": "array", "items": {"type": "string"}},
            "is_technical": {"type": "boolean"},
            "experience_years": {"type": "number"},
            "availability_hours_per_week": {"type": "number"},
            "timezone": {"type": "string"},
            "interests": {"type": "array", "items": {"type": "string"}},
            "career_goals": {"type": "string"},
            "resume_summary": {"type": "string"},
        },
        "required": ["name"],
    },
)
async def people_upsert(ctx, args: dict) -> dict:
    person = await ctx.db.scalar(
        select(Person).where(
            Person.workspace_id == ctx.workspace_id,
            func.lower(Person.name) == args["name"].lower(),
        )
    )
    if person is None:
        person = Person(
            workspace_id=ctx.workspace_id,
            name=args["name"],
            role=PersonRole(args.get("role", "other")),
        )
        ctx.db.add(person)
        await ctx.db.flush()
        created = True
    else:
        created = False

    updatable = [
        "role", "title", "skills", "languages", "is_technical",
        "experience_years", "availability_hours_per_week", "timezone",
        "interests", "career_goals", "resume_summary",
    ]
    for field in updatable:
        if field in args:
            if field == "role":
                setattr(person, field, PersonRole(args[field]))
            else:
                setattr(person, field, args[field])
    await ctx.db.flush()
    return {"person_id": str(person.id), "name": person.name, "created": created}


@tool(
    name="people_get",
    description="Get a person's full profile, including their facts and reliability.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)
async def people_get(ctx, args: dict) -> dict:
    person = await ctx.db.scalar(
        select(Person).where(
            Person.workspace_id == ctx.workspace_id,
            func.lower(Person.name) == args["name"].lower(),
        )
    )
    if not person:
        return {"error": "person not found"}

    facts = (await ctx.db.scalars(
        select(Fact).where(
            Fact.workspace_id == ctx.workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.subject) == args["name"].lower(),
        ).order_by(Fact.created_at.desc()).limit(50)
    )).all()

    commitments = [f for f in facts if f.fact_kind == FactKind.COMMITMENT]
    completed = [f for f in facts if f.fact_kind == FactKind.STATUS_UPDATE
                 and "done" in f.value.lower()]
    missed = [f for f in facts if f.fact_kind == FactKind.BLOCKER]
    reliability = (
        round(len(completed) / max(len(commitments), 1), 2)
        if commitments else None
    )

    return {
        "name": person.name,
        "role": person.role.value,
        "title": person.title,
        "skills": person.skills,
        "languages": person.languages,
        "is_technical": person.is_technical,
        "experience_years": person.experience_years,
        "availability_hours_per_week": person.availability_hours_per_week,
        "timezone": person.timezone,
        "interests": person.interests,
        "career_goals": person.career_goals,
        "resume_summary": person.resume_summary,
        "email": person.email,
        "slack_id": person.slack_id,
        "slack_handle": person.slack_handle,
        "github_login": person.github_login,
        "jira_account_id": person.jira_account_id,
        "jira_display_name": person.jira_display_name,
        "linear_id": person.linear_id,
        "avatar_url": person.avatar_url,
        "reliability": {
            "score": reliability,
            "commitments": len(commitments),
            "completed": len(completed),
            "blockers": len(missed),
        },
        "recent_facts": [
            {"predicate": f.predicate, "value": f.value, "kind": f.fact_kind.value}
            for f in facts[:10]
        ],
    }


@tool(
    name="people_list",
    description="List everyone the agent knows about in this workspace.",
    parameters={
        "type": "object",
        "properties": {
            "role": {"type": "string", "enum": [r.value for r in PersonRole]},
        },
    },
)
async def people_list(ctx, args: dict) -> dict:
    stmt = select(Person).where(Person.workspace_id == ctx.workspace_id)
    if args.get("role"):
        stmt = stmt.where(Person.role == PersonRole(args["role"]))
    people = (await ctx.db.scalars(stmt)).all()
    return {
        "count": len(people),
        "people": [
            {
                "person_id": str(p.id),
                "name": p.name,
                "role": p.role.value,
                "title": p.title,
                "skills_count": len(p.skills),
                "email": p.email,
                "slack_handle": p.slack_handle,
                "github_login": p.github_login,
                "jira_account_id": p.jira_account_id,
                "linear_id": p.linear_id,
                "integrations_linked": sum([
                    bool(p.slack_id), bool(p.github_login),
                    bool(p.jira_account_id), bool(p.linear_id),
                ]),
            }
            for p in people
        ],
    }


@tool(
    name="projects_upsert",
    description="Create or update a project the agent should track.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["planning", "active", "on_hold", "completed", "cancelled"],
                "default": "planning",
            },
            "deadline": {"type": "string", "description": "ISO date or freeform"},
        },
        "required": ["name"],
    },
)
async def projects_upsert(ctx, args: dict) -> dict:
    from ..models.memory import ProjectStatus
    project = await ctx.db.scalar(
        select(Project).where(
            Project.workspace_id == ctx.workspace_id,
            func.lower(Project.name) == args["name"].lower(),
        )
    )
    if project is None:
        project = Project(
            workspace_id=ctx.workspace_id,
            name=args["name"],
        )
        ctx.db.add(project)
        await ctx.db.flush()
        created = True
    else:
        created = False
    if "description" in args:
        project.description = args["description"]
    if "status" in args:
        project.status = ProjectStatus(args["status"])
    if "deadline" in args:
        project.deadline = args["deadline"]
    await ctx.db.flush()
    return {"project_id": str(project.id), "name": project.name, "created": created}


@tool(
    name="projects_list",
    description="List all projects the agent tracks in this workspace.",
    parameters={"type": "object", "properties": {}},
)
async def projects_list(ctx, args: dict) -> dict:
    projects = (await ctx.db.scalars(
        select(Project).where(Project.workspace_id == ctx.workspace_id)
    )).all()
    return {
        "count": len(projects),
        "projects": [
            {
                "project_id": str(p.id),
                "name": p.name,
                "status": p.status.value,
                "deadline": p.deadline,
            }
            for p in projects
        ],
    }
