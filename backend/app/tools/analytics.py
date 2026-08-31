"""Analytics tools. The agent can query workspace analytics to answer
questions like 'how is the project going?', 'who is good at what?', 'where
are we stuck?', and 'what needs attention?'.
"""
from __future__ import annotations

from sqlalchemy import desc, func, select
from datetime import datetime, timedelta, UTC

from ..agent.registry import tool
from ..models.meetings import Meeting, MeetingStatus
from ..models.memory import (
    Alert, Fact, FactKind, MemoryTask, MemoryTaskStatus,
    Person, Project, ProjectStatus, TemporalStatus,
)
from ..models.work import Task, TaskState


@tool(
    name="analytics_overview",
    description=(
        "Get a high-level analytics overview of the workspace: task counts, "
        "completion rate, active projects, open alerts, and team size. "
        "Use this when the user asks 'how are things going?' or wants a summary."
    ),
    parameters={"type": "object", "properties": {}},
)
async def analytics_overview(ctx, args: dict) -> dict:
    # Task counts
    task_rows = (await ctx.db.execute(
        select(Task.state, func.count(Task.id))
        .where(Task.workspace_id == ctx.workspace_id)
        .group_by(Task.state)
    )).all()
    task_counts = {r[0].value if r[0] else "unknown": r[1] for r in task_rows}
    total_tasks = sum(task_counts.values())

    # People count
    people_count = await ctx.db.scalar(
        select(func.count(Person.id)).where(Person.workspace_id == ctx.workspace_id)
    ) or 0

    # Active projects
    projects = (await ctx.db.scalars(
        select(Project).where(
            Project.workspace_id == ctx.workspace_id,
            Project.status == ProjectStatus.ACTIVE,
        )
    )).all()

    # Open alerts
    alert_count = await ctx.db.scalar(
        select(func.count(Alert.id)).where(
            Alert.workspace_id == ctx.workspace_id,
            Alert.status == "open",
        )
    ) or 0

    # Overdue tasks
    now = datetime.now(UTC)
    overdue = await ctx.db.scalar(
        select(func.count(Task.id)).where(
            Task.workspace_id == ctx.workspace_id,
            Task.due_at < now,
            Task.state.notin_([TaskState.COMPLETED, TaskState.CANCELLED]),
        )
    ) or 0

    completed = task_counts.get("completed", 0)
    return {
        "total_tasks": total_tasks,
        "completed": completed,
        "in_progress": task_counts.get("in_progress", 0),
        "blocked": task_counts.get("blocked", 0),
        "overdue": overdue,
        "completion_rate": round(completed / total_tasks, 2) if total_tasks > 0 else 0,
        "active_projects": len(projects),
        "project_names": [p.name for p in projects],
        "team_size": people_count,
        "open_alerts": alert_count,
    }


@tool(
    name="analytics_project_health",
    description=(
        "Get detailed health metrics for all projects: progress percentage, "
        "blocked tasks, deadlines. Use this when the user asks about project "
        "progress or which projects are at risk."
    ),
    parameters={"type": "object", "properties": {}},
)
async def analytics_project_health(ctx, args: dict) -> dict:
    projects = (await ctx.db.scalars(
        select(Project).where(Project.workspace_id == ctx.workspace_id)
    )).all()
    result = []
    for p in projects:
        total = await ctx.db.scalar(
            select(func.count(MemoryTask.id))
            .where(MemoryTask.project_id == p.id)
        ) or 0
        done = await ctx.db.scalar(
            select(func.count(MemoryTask.id))
            .where(MemoryTask.project_id == p.id, MemoryTask.status == MemoryTaskStatus.DONE)
        ) or 0
        blocked = await ctx.db.scalar(
            select(func.count(MemoryTask.id))
            .where(MemoryTask.project_id == p.id, MemoryTask.status == MemoryTaskStatus.BLOCKED)
        ) or 0
        progress = round(done / total, 2) if total > 0 else 0
        result.append({
            "name": p.name,
            "status": p.status.value,
            "deadline": p.deadline,
            "total_tasks": total,
            "completed": done,
            "blocked": blocked,
            "progress": progress,
            "health": (
                "blocked" if blocked > 0 and total > 0 and blocked / total > 0.3
                else "on_track" if progress >= 0.5
                else "at_risk" if total > 0
                else "planning"
            ),
        })
    return {"projects": result}


@tool(
    name="analytics_team_skills",
    description=(
        "Get team skills breakdown — who is good at what, reliability scores, "
        "and integration coverage. Use this when the user asks about team "
        "capabilities, who should work on what, or who is reliable."
    ),
    parameters={"type": "object", "properties": {}},
)
async def analytics_team_skills(ctx, args: dict) -> dict:
    people = (await ctx.db.scalars(
        select(Person).where(Person.workspace_id == ctx.workspace_id)
    )).all()
    skill_map: dict[str, list[str]] = {}
    for p in people:
        for skill in (p.skills or []):
            s = skill.lower() if isinstance(skill, str) else str(skill).lower()
            if s not in skill_map:
                skill_map[s] = []
            skill_map[s].append(p.name)

    top_skills = sorted(
        [{"skill": k, "count": len(v), "people": v} for k, v in skill_map.items()],
        key=lambda x: x["count"], reverse=True,
    )[:10]

    # Reliability per person
    reliability = []
    for p in people:
        commitments = await ctx.db.scalar(
            select(func.count(Fact.id)).where(
                Fact.workspace_id == ctx.workspace_id,
                Fact.temporal_status == TemporalStatus.CURRENT,
                func.lower(Fact.subject) == p.name.lower(),
                Fact.fact_kind == FactKind.COMMITMENT,
            )
        ) or 0
        completed = await ctx.db.scalar(
            select(func.count(Fact.id)).where(
                Fact.workspace_id == ctx.workspace_id,
                Fact.temporal_status == TemporalStatus.CURRENT,
                func.lower(Fact.subject) == p.name.lower(),
                Fact.fact_kind == FactKind.STATUS_UPDATE,
            )
        ) or 0
        blockers = await ctx.db.scalar(
            select(func.count(Fact.id)).where(
                Fact.workspace_id == ctx.workspace_id,
                Fact.temporal_status == TemporalStatus.CURRENT,
                func.lower(Fact.subject) == p.name.lower(),
                Fact.fact_kind == FactKind.BLOCKER,
            )
        ) or 0
        score = round(completed / max(commitments, 1), 2) if commitments > 0 else None
        reliability.append({
            "name": p.name,
            "role": p.role.value,
            "skills": p.skills or [],
            "commitments": commitments,
            "completed": completed,
            "blockers": blockers,
            "reliability_score": score,
            "integrations": {
                "slack": bool(p.slack_id),
                "github": bool(p.github_login),
                "jira": bool(p.jira_account_id),
                "linear": bool(p.linear_id),
            },
        })
    return {
        "total_people": len(people),
        "top_skills": top_skills,
        "people": reliability,
    }


@tool(
    name="analytics_bottlenecks",
    description=(
        "Find where the project is stuck: blocked tasks, overdue tasks, "
        "active alerts, and people with blockers. Use this when the user "
        "asks 'what's blocking us?' or 'where are we stuck?'."
    ),
    parameters={"type": "object", "properties": {}},
)
async def analytics_bottlenecks(ctx, args: dict) -> dict:
    now = datetime.now(UTC)

    # Blocked tasks
    blocked = (await ctx.db.scalars(
        select(Task).where(
            Task.workspace_id == ctx.workspace_id,
            Task.state == TaskState.BLOCKED,
        )
    )).all()

    # Overdue tasks
    overdue = (await ctx.db.scalars(
        select(Task).where(
            Task.workspace_id == ctx.workspace_id,
            Task.due_at < now,
            Task.state.notin_([TaskState.COMPLETED, TaskState.CANCELLED]),
        ).order_by(Task.due_at)
    )).all()

    # Active alerts
    alerts = (await ctx.db.scalars(
        select(Alert).where(
            Alert.workspace_id == ctx.workspace_id,
            Alert.status == "open",
        ).order_by(desc(Alert.created_at)).limit(10)
    )).all()

    return {
        "blocked_tasks": [
            {"title": t.title, "state": t.state.value, "due_at": t.due_at.isoformat() if t.due_at else None}
            for t in blocked
        ],
        "overdue_tasks": [
            {
                "title": t.title,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "days_overdue": (now - t.due_at).days if t.due_at else 0,
            }
            for t in overdue
        ],
        "alerts": [
            {"type": a.alert_type, "severity": a.severity, "message": a.message, "person": a.person}
            for a in alerts
        ],
        "total_bottlenecks": len(blocked) + len(overdue) + len(alerts),
    }
