"""Analytics endpoint. Aggregates project progress, team skills, bottlenecks,
and key metrics into a single response for the analytics dashboard.
"""
import uuid
from datetime import datetime, timedelta, UTC
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.meetings import Meeting, MeetingStatus
from ...models.memory import (
    Alert, Fact, FactKind, MemoryTask, MemoryTaskStatus,
    Person, PersonRole, Project, ProjectStatus, TemporalStatus,
)
from ...models.work import Task, TaskState

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _check_member(workspace_id, user: User, session: AsyncSession) -> None:
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        raise HTTPException(403, "Not a member of this workspace")


@router.get("")
async def get_analytics(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get a comprehensive analytics overview for the workspace."""
    await _check_member(workspace_id, user, session)

    # ── Task metrics ──────────────────────────────────────────────
    task_counts = await _task_counts(session, workspace_id)
    task_velocity = await _task_velocity(session, workspace_id)
    overdue_tasks = await _overdue_tasks(session, workspace_id)

    # ── Project progress ──────────────────────────────────────────
    projects = await _project_progress(session, workspace_id)

    # ── Team skills & reliability ─────────────────────────────────
    team_skills = await _team_skills(session, workspace_id)
    person_reliability = await _person_reliability(session, workspace_id)

    # ── Bottlenecks & alerts ──────────────────────────────────────
    alerts = await _active_alerts(session, workspace_id)
    blocked_tasks = await _blocked_tasks(session, workspace_id)

    # ── Meeting metrics ───────────────────────────────────────────
    meeting_stats = await _meeting_stats(session, workspace_id)

    # ── Activity over time ────────────────────────────────────────
    activity_timeline = await _activity_timeline(session, workspace_id)

    # ── Integration coverage ──────────────────────────────────────
    integration_coverage = await _integration_coverage(session, workspace_id)

    return {
        "workspace_id": str(workspace_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "total_tasks": task_counts["total"],
            "completed_tasks": task_counts["completed"],
            "open_tasks": task_counts["open"],
            "blocked_tasks": task_counts["blocked"],
            "overdue_count": len(overdue_tasks),
            "completion_rate": (
                round(task_counts["completed"] / task_counts["total"], 2)
                if task_counts["total"] > 0 else 0
            ),
            "total_people": team_skills["total_people"],
            "active_projects": len([p for p in projects if p["status"] == "active"]),
            "open_alerts": len(alerts),
            "meetings_this_week": meeting_stats["this_week"],
        },
        "task_metrics": task_counts,
        "task_velocity": task_velocity,
        "overdue_tasks": overdue_tasks,
        "projects": projects,
        "team_skills": team_skills,
        "person_reliability": person_reliability,
        "alerts": alerts,
        "blocked_tasks": blocked_tasks,
        "meeting_stats": meeting_stats,
        "activity_timeline": activity_timeline,
        "integration_coverage": integration_coverage,
    }


# ── Helpers ────────────────────────────────────────────────────────────

async def _task_counts(session: AsyncSession, ws_id: uuid.UUID) -> dict:
    """Count tasks by state."""
    rows = (await session.execute(
        select(Task.state, func.count(Task.id))
        .where(Task.workspace_id == ws_id)
        .group_by(Task.state)
    )).all()
    counts = {r[0].value if r[0] else "unknown": r[1] for r in rows}
    total = sum(counts.values())
    return {
        "total": total,
        "open": counts.get("open", 0),
        "in_progress": counts.get("in_progress", 0),
        "blocked": counts.get("blocked", 0),
        "completed": counts.get("completed", 0),
        "cancelled": counts.get("cancelled", 0),
        "overdue": counts.get("overdue", 0),
    }


async def _task_velocity(session: AsyncSession, ws_id: uuid.UUID) -> list[dict]:
    """Tasks created vs completed per day for the last 14 days."""
    now = datetime.now(UTC)
    start = now - timedelta(days=14)
    created = (await session.execute(
        select(func.date(Task.created_at), func.count(Task.id))
        .where(Task.workspace_id == ws_id, Task.created_at >= start)
        .group_by(func.date(Task.created_at))
        .order_by(func.date(Task.created_at))
    )).all()
    completed = (await session.execute(
        select(func.date(Task.last_activity_at), func.count(Task.id))
        .where(
            Task.workspace_id == ws_id,
            Task.state == TaskState.COMPLETED,
            Task.last_activity_at >= start,
        )
        .group_by(func.date(Task.last_activity_at))
        .order_by(func.date(Task.last_activity_at))
    )).all()
    created_map = {str(r[0]): r[1] for r in created}
    completed_map = {str(r[0]): r[1] for r in completed}
    timeline = []
    for i in range(14):
        day = (now - timedelta(days=13 - i)).strftime("%Y-%m-%d")
        timeline.append({
            "date": day,
            "created": created_map.get(day, 0),
            "completed": completed_map.get(day, 0),
        })
    return timeline


async def _overdue_tasks(session: AsyncSession, ws_id: uuid.UUID) -> list[dict]:
    """Tasks that are past their due date and not completed."""
    now = datetime.now(UTC)
    tasks = (await session.scalars(
        select(Task).where(
            Task.workspace_id == ws_id,
            Task.due_at < now,
            Task.state.notin_([TaskState.COMPLETED, TaskState.CANCELLED]),
        ).order_by(Task.due_at)
    )).all()
    return [
        {
            "id": str(t.id),
            "title": t.title,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "state": t.state.value,
            "days_overdue": (now - (t.due_at.replace(tzinfo=UTC) if t.due_at.tzinfo is None else t.due_at)).days if t.due_at else 0,
        }
        for t in tasks
    ]


async def _project_progress(session: AsyncSession, ws_id: uuid.UUID) -> list[dict]:
    """Project progress with task counts and health score."""
    projects = (await session.scalars(
        select(Project).where(Project.workspace_id == ws_id)
    )).all()
    result = []
    for p in projects:
        # Count memory tasks for this project
        total = await session.scalar(
            select(func.count(MemoryTask.id))
            .where(MemoryTask.project_id == p.id)
        ) or 0
        done = await session.scalar(
            select(func.count(MemoryTask.id))
            .where(MemoryTask.project_id == p.id, MemoryTask.status == MemoryTaskStatus.DONE)
        ) or 0
        blocked = await session.scalar(
            select(func.count(MemoryTask.id))
            .where(MemoryTask.project_id == p.id, MemoryTask.status == MemoryTaskStatus.BLOCKED)
        ) or 0
        progress = round(done / total, 2) if total > 0 else 0
        result.append({
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "status": p.status.value,
            "deadline": p.deadline,
            "total_tasks": total,
            "completed_tasks": done,
            "blocked_tasks": blocked,
            "progress": progress,
            "health": (
                "blocked" if blocked > 0 and total > 0 and blocked / total > 0.3
                else "on_track" if progress >= 0.5
                else "at_risk" if total > 0
                else "planning"
            ),
        })
    return result


async def _team_skills(session: AsyncSession, ws_id: uuid.UUID) -> dict:
    """Aggregate skills across all people, and identify who is good at what."""
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == ws_id)
    )).all()
    skill_map: dict[str, list[str]] = {}
    for p in people:
        for skill in (p.skills or []):
            skill_lower = skill.lower() if isinstance(skill, str) else str(skill).lower()
            if skill_lower not in skill_map:
                skill_map[skill_lower] = []
            skill_map[skill_lower].append(p.name)

    top_skills = sorted(
        [{"skill": k, "count": len(v), "people": v} for k, v in skill_map.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:15]

    return {
        "total_people": len(people),
        "skills": top_skills,
        "people": [
            {
                "name": p.name,
                "role": p.role.value,
                "title": p.title,
                "skills": p.skills or [],
                "integrations_linked": sum([
                    bool(p.slack_id), bool(p.github_login),
                    bool(p.jira_account_id), bool(p.linear_id),
                ]),
                "avatar_url": p.avatar_url,
                "timezone": p.timezone,
            }
            for p in people
        ],
    }


async def _person_reliability(session: AsyncSession, ws_id: uuid.UUID) -> list[dict]:
    """Reliability score per person based on commitments vs completed."""
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == ws_id)
    )).all()
    result = []
    for p in people:
        commitments = await session.scalar(
            select(func.count(Fact.id)).where(
                Fact.workspace_id == ws_id,
                Fact.temporal_status == TemporalStatus.CURRENT,
                func.lower(Fact.subject) == p.name.lower(),
                Fact.fact_kind == FactKind.COMMITMENT,
            )
        ) or 0
        completed = await session.scalar(
            select(func.count(Fact.id)).where(
                Fact.workspace_id == ws_id,
                Fact.temporal_status == TemporalStatus.CURRENT,
                func.lower(Fact.subject) == p.name.lower(),
                Fact.fact_kind == FactKind.STATUS_UPDATE,
            )
        ) or 0
        blockers = await session.scalar(
            select(func.count(Fact.id)).where(
                Fact.workspace_id == ws_id,
                Fact.temporal_status == TemporalStatus.CURRENT,
                func.lower(Fact.subject) == p.name.lower(),
                Fact.fact_kind == FactKind.BLOCKER,
            )
        ) or 0
        score = round(completed / max(commitments, 1), 2) if commitments > 0 else None
        result.append({
            "name": p.name,
            "role": p.role.value,
            "commitments": commitments,
            "completed": completed,
            "blockers": blockers,
            "reliability_score": score,
        })
    # Sort by reliability score (highest first), None last
    result.sort(key=lambda x: x["reliability_score"] if x["reliability_score"] is not None else -1, reverse=True)
    return result


async def _active_alerts(session: AsyncSession, ws_id: uuid.UUID) -> list[dict]:
    """Active risk alerts."""
    alerts = (await session.scalars(
        select(Alert).where(
            Alert.workspace_id == ws_id,
            Alert.status == "open",
        ).order_by(desc(Alert.created_at)).limit(20)
    )).all()
    return [
        {
            "id": str(a.id),
            "type": a.alert_type,
            "subject": a.subject,
            "severity": a.severity,
            "message": a.message,
            "project": a.project,
            "person": a.person,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]


async def _blocked_tasks(session: AsyncSession, ws_id: uuid.UUID) -> list[dict]:
    """Tasks that are blocked — the 'where the project is stuck' view."""
    tasks = (await session.scalars(
        select(Task).where(
            Task.workspace_id == ws_id,
            Task.state == TaskState.BLOCKED,
        ).order_by(desc(Task.created_at))
    )).all()
    memory_blocked = (await session.scalars(
        select(MemoryTask).where(
            MemoryTask.workspace_id == ws_id,
            MemoryTask.status == MemoryTaskStatus.BLOCKED,
        ).order_by(desc(MemoryTask.created_at))
    )).all()
    result = [
        {
            "id": str(t.id),
            "title": t.title,
            "state": t.state.value,
            "source": "work_task",
            "due_at": t.due_at.isoformat() if t.due_at else None,
        }
        for t in tasks
    ]
    result.extend([
        {
            "id": str(t.id),
            "title": t.title,
            "state": t.status.value,
            "source": "memory_task",
            "due_at": t.deadline,
        }
        for t in memory_blocked
    ])
    return result


async def _meeting_stats(session: AsyncSession, ws_id: uuid.UUID) -> dict:
    """Meeting statistics."""
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    total = await session.scalar(
        select(func.count(Meeting.id)).where(Meeting.workspace_id == ws_id)
    ) or 0
    this_week = await session.scalar(
        select(func.count(Meeting.id)).where(
            Meeting.workspace_id == ws_id,
            Meeting.created_at >= week_ago,
        )
    ) or 0
    completed = await session.scalar(
        select(func.count(Meeting.id)).where(
            Meeting.workspace_id == ws_id,
            Meeting.status == MeetingStatus.ENDED,
        )
    ) or 0
    return {
        "total": total,
        "this_week": this_week,
        "completed": completed,
    }


async def _activity_timeline(session: AsyncSession, ws_id: uuid.UUID) -> list[dict]:
    """Facts created per day for the last 14 days — shows activity level."""
    now = datetime.now(UTC)
    start = now - timedelta(days=14)
    rows = (await session.execute(
        select(func.date(Fact.created_at), func.count(Fact.id))
        .where(Fact.workspace_id == ws_id, Fact.created_at >= start)
        .group_by(func.date(Fact.created_at))
        .order_by(func.date(Fact.created_at))
    )).all()
    fact_map = {str(r[0]): r[1] for r in rows}
    timeline = []
    for i in range(14):
        day = (now - timedelta(days=13 - i)).strftime("%Y-%m-%d")
        timeline.append({
            "date": day,
            "facts": fact_map.get(day, 0),
        })
    return timeline


async def _integration_coverage(session: AsyncSession, ws_id: uuid.UUID) -> dict:
    """How many people are linked to each integration."""
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == ws_id)
    )).all()
    total = len(people)
    return {
        "total_people": total,
        "slack": sum(1 for p in people if p.slack_id),
        "github": sum(1 for p in people if p.github_login),
        "jira": sum(1 for p in people if p.jira_account_id),
        "linear": sum(1 for p in people if p.linear_id),
        "email": sum(1 for p in people if p.email),
    }
