"""Sprint planning, retrospectives, milestones, and capacity forecasting.

Ports CloseLoopAI's sprints module into the Autogent backend.
"""
from __future__ import annotations

import logging
import time
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.llm import LLMError, get_llm
from ..agent.parsing import parse_json_response
from ..agent.prompts import RETROSPECTIVE_PROMPT, SPRINT_PLANNING_PROMPT
from ..models.memory import (
    Fact, FactKind, MemoryTask, MemoryTaskStatus, Milestone,
    Person, Project, Sprint, TemporalStatus,
)

log = logging.getLogger(__name__)
HOURS_PER_DAY = 8
OVERCOMMIT_THRESHOLD = 0.8
_OPEN = (MemoryTaskStatus.OPEN, MemoryTaskStatus.IN_PROGRESS, MemoryTaskStatus.BLOCKED)


async def create_sprint(
    session: AsyncSession, workspace_id: uuid_lib.UUID, project: str, goal: str,
    sprint_days: int = 14, start_date: datetime | None = None,
) -> dict[str, Any]:
    """Create a new sprint row in 'planning' status."""
    start = start_date or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(days=sprint_days)
    sid = f"sprint:{uuid_lib.uuid4().hex[:12]}"
    session.add(Sprint(workspace_id=workspace_id, sprint_id=sid, project=project,
                       goal=goal, start_date=start, end_date=end, status="planning", task_ids=[]))
    await session.flush()
    return {"sprint_id": sid, "project": project, "goal": goal,
            "start_date": start.isoformat(), "end_date": end.isoformat(), "status": "planning"}


async def plan_sprint(
    session: AsyncSession, workspace_id: uuid_lib.UUID, sprint_id: str,
) -> dict[str, Any]:
    """AI-plan which tasks go in the sprint. Falls back to capacity-based selection."""
    started = time.perf_counter()
    sprint = await session.scalar(select(Sprint).where(
        Sprint.workspace_id == workspace_id, Sprint.sprint_id == sprint_id))
    if sprint is None:
        raise ValueError(f"Sprint not found: {sprint_id}")
    proj = await _get_project_by_name(session, workspace_id, sprint.project)
    open_tasks: list[MemoryTask] = []
    if proj is not None:
        open_tasks = [t for t in (await session.scalars(
            select(MemoryTask).where(MemoryTask.workspace_id == workspace_id,
                                      MemoryTask.project_id == proj.id))).all() if t.status in _OPEN]
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == workspace_id))).all()
    sprint_days = max(1, (sprint.end_date - sprint.start_date).days)
    cap_days = sum((p.availability_hours_per_week or 0) for p in people) * sprint_days / 7
    tasks_brief = [{"task_id": str(t.id), "title": t.title, "estimated_days": t.estimated_days,
                    "required_skills": t.required_skills, "status": t.status.value} for t in open_tasks]
    team_brief = [{"name": p.name, "role": p.role.value, "skills": p.skills,
                   "availability_hours_per_week": p.availability_hours_per_week} for p in people]
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    sprint_goal, cap_util, risk_notes = sprint.goal, 0.0, []

    try:
        prompt = SPRINT_PLANNING_PROMPT.format(
            project=sprint.project, sprint_days=sprint_days,
            capacity=f"{cap_days:.1f} person-days", tasks=tasks_brief,
            team=team_brief, remaining_work="(none)")
        payload = parse_json_response(await get_llm().complete(prompt, max_tokens=2000))
        if not isinstance(payload, dict):
            raise ValueError("Plan payload is not an object")
        sprint_goal = payload.get("sprint_goal", sprint.goal)
        selected = payload.get("selected_tasks") or []
        deferred = payload.get("deferred_tasks") or []
        cap_util = float(payload.get("capacity_utilization") or 0)
        risk_notes = payload.get("risk_notes") or []
    except Exception as exc:
        log.warning("Sprint planning LLM failed for %s: %s", sprint_id, exc)
        selected, deferred, cap_util = _fallback_plan(open_tasks, people, cap_days)
        risk_notes = ["LLM planning unavailable; used capacity-based fallback"]

    sprint.task_ids = [str(s["task_id"]) for s in selected if s.get("task_id")]
    sprint.status = "active"
    await session.flush()
    return {"sprint_goal": sprint_goal, "selected_tasks": selected, "deferred_tasks": deferred,
            "capacity_utilization": cap_util, "risk_notes": risk_notes,
            "elapsed_ms": int((time.perf_counter() - started) * 1000)}


def _fallback_plan(tasks: list[MemoryTask], people: list[Person],
                   cap_days: float) -> tuple[list[dict], list[dict], float]:
    """Simple capacity-based selection: sort by estimate, fill to 80%."""
    budget = cap_days * OVERCOMMIT_THRESHOLD
    names = [p.name for p in people] or ["unassigned"]
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    used = 0.0
    for idx, task in enumerate(sorted(tasks, key=lambda t: t.estimated_days or 1.0)):
        est = task.estimated_days or 1.0
        if used + est <= budget:
            selected.append({"task_id": str(task.id), "assignee": names[idx % len(names)],
                             "rationale": "capacity-based selection"})
            used += est
        else:
            deferred.append({"task_id": str(task.id), "reason": "exceeds remaining sprint capacity"})
    return selected, deferred, round(used / cap_days if cap_days > 0 else 0.0, 2)


async def get_sprint(
    session: AsyncSession, workspace_id: uuid_lib.UUID, sprint_id: str,
) -> dict[str, Any]:
    """Return sprint details with full task objects."""
    sprint = await session.scalar(select(Sprint).where(
        Sprint.workspace_id == workspace_id, Sprint.sprint_id == sprint_id))
    if sprint is None:
        raise ValueError(f"Sprint not found: {sprint_id}")
    tasks: list[dict[str, Any]] = []
    ids = sprint.task_ids or []
    if ids:
        rows = (await session.scalars(select(MemoryTask).where(
            MemoryTask.workspace_id == workspace_id,
            MemoryTask.id.in_([uuid_lib.UUID(tid) for tid in ids])))).all()
        tasks = [{"task_id": str(t.id), "title": t.title, "status": t.status.value,
                  "estimated_days": t.estimated_days, "required_skills": t.required_skills,
                  "deadline": t.deadline} for t in rows]
    return {"sprint_id": sprint.sprint_id, "project": sprint.project, "goal": sprint.goal,
            "start_date": sprint.start_date.isoformat() if sprint.start_date else None,
            "end_date": sprint.end_date.isoformat() if sprint.end_date else None,
            "status": sprint.status, "tasks": tasks}


async def list_sprints(
    session: AsyncSession, workspace_id: uuid_lib.UUID, project: str | None = None,
) -> list[dict[str, Any]]:
    """List sprints, optionally filtered by project, newest first."""
    stmt = select(Sprint).where(Sprint.workspace_id == workspace_id).order_by(desc(Sprint.start_date))
    if project:
        stmt = stmt.where(Sprint.project == project)
    return [{"sprint_id": r.sprint_id, "project": r.project, "goal": r.goal,
             "start_date": r.start_date.isoformat() if r.start_date else None,
             "end_date": r.end_date.isoformat() if r.end_date else None,
             "status": r.status, "task_count": len(r.task_ids or [])}
            for r in (await session.scalars(stmt)).all()]


async def review_sprint(
    session: AsyncSession, workspace_id: uuid_lib.UUID, sprint_id: str,
) -> dict[str, Any]:
    """Run a sprint retrospective via LLM. Stores lessons as Facts, marks sprint completed."""
    started = time.perf_counter()
    sprint = await session.scalar(select(Sprint).where(
        Sprint.workspace_id == workspace_id, Sprint.sprint_id == sprint_id))
    if sprint is None:
        raise ValueError(f"Sprint not found: {sprint_id}")
    sprint_tasks: list[MemoryTask] = []
    ids = sprint.task_ids or []
    if ids:
        sprint_tasks = list((await session.scalars(select(MemoryTask).where(
            MemoryTask.workspace_id == workspace_id,
            MemoryTask.id.in_([uuid_lib.UUID(tid) for tid in ids])))).all())
    people_map = {p.id: p.name for p in (await session.scalars(
        select(Person).where(Person.workspace_id == workspace_id))).all()}
    completed = [t for t in sprint_tasks if t.status == MemoryTaskStatus.DONE]
    missed = [t for t in sprint_tasks
              if t.status not in (MemoryTaskStatus.DONE, MemoryTaskStatus.CANCELLED)]

    blockers = (await session.scalars(select(Fact).where(
        Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.BLOCKER,
        Fact.temporal_status == TemporalStatus.CURRENT, Fact.project == sprint.project,
        Fact.valid_from >= sprint.start_date, Fact.valid_from <= sprint.end_date))).all()
    blocker_texts = [b.value for b in blockers]
    performance: dict[str, dict[str, int]] = {}
    for t in sprint_tasks:
        name = people_map.get(t.assignee_person_id, "unassigned")
        bucket = performance.setdefault(name, {"completed": 0, "missed": 0})
        if t.status == MemoryTaskStatus.DONE:
            bucket["completed"] += 1
        elif t.status != MemoryTaskStatus.CANCELLED:
            bucket["missed"] += 1
    well: list[str] = []
    didnt: list[str] = []
    change: list[str] = []
    lessons: list[str] = []
    verdict = "partial"

    try:
        prompt = RETROSPECTIVE_PROMPT.format(
            sprint_goal=sprint.goal, start_date=sprint.start_date.isoformat(),
            end_date=sprint.end_date.isoformat(),
            planned=[t.title for t in sprint_tasks],
            completed=[t.title for t in completed],
            missed=[t.title for t in missed], blockers=blocker_texts,
            performance=performance)
        payload = parse_json_response(await get_llm().complete(prompt, max_tokens=2000))
        if not isinstance(payload, dict):
            raise ValueError("Retrospective payload is not an object")
        well = payload.get("what_went_well") or []
        didnt = payload.get("what_didnt_go_well") or []
        change = payload.get("what_to_change") or []
        lessons = payload.get("lessons_learned") or []
        verdict = payload.get("sprint_verdict", "partial")
    except Exception as exc:
        log.warning("Retrospective LLM failed for %s: %s", sprint_id, exc)
        well, didnt, change, verdict = _fallback_retrospective(completed, missed, blocker_texts)

    now = datetime.now(timezone.utc)
    for lesson in lessons:
        session.add(Fact(workspace_id=workspace_id, fact_id=str(uuid_lib.uuid4()),
                         subject=sprint.sprint_id, predicate="lesson learned",
                         value=str(lesson), fact_kind=FactKind.DECISION,
                         project=sprint.project, temporal_status=TemporalStatus.CURRENT,
                         valid_from=now, speaker="system"))
    sprint.status = "completed"
    await session.flush()
    return {"what_went_well": well, "what_didnt_go_well": didnt,
            "what_to_change": change, "lessons_learned": lessons,
            "sprint_verdict": verdict,
            "elapsed_ms": int((time.perf_counter() - started) * 1000)}


def _fallback_retrospective(completed: list[MemoryTask], missed: list[MemoryTask],
                            blockers: list[str]) -> tuple[list[str], list[str], list[str], str]:
    """Deterministic retrospective verdict when LLM is unavailable."""
    total = len(completed) + len(missed)
    if total == 0:
        return [], [], [], "partial"
    rate = len(completed) / total
    verdict = "success" if rate >= 0.8 else "partial" if rate >= 0.4 else "failed"
    well = [f"Completed {len(completed)} of {total} planned tasks"] if completed else []
    didnt: list[str] = []
    if missed:
        didnt.append(f"Missed {len(missed)} tasks")
    if blockers:
        didnt.append(f"Encountered {len(blockers)} blockers")
    change: list[str] = []
    if missed:
        change.append("Reduce sprint scope or add capacity")
    if blockers:
        change.append("Address blockers earlier in the sprint")
    return well, didnt, change, verdict


async def create_milestone(
    session: AsyncSession, workspace_id: uuid_lib.UUID, project: str,
    title: str, target_date: str, description: str | None = None,
) -> dict[str, Any]:
    """Create a new milestone row."""
    mid = f"milestone:{uuid_lib.uuid4().hex[:12]}"
    session.add(Milestone(workspace_id=workspace_id, milestone_id=mid, project=project,
                          title=title, target_date=target_date,
                          description=description, status="upcoming"))
    await session.flush()
    return {"milestone_id": mid, "project": project, "title": title,
            "target_date": target_date, "description": description, "status": "upcoming"}


async def list_milestones(
    session: AsyncSession, workspace_id: uuid_lib.UUID, project: str | None = None,
) -> list[dict[str, Any]]:
    """List milestones with task progress. Marks overdue milestones."""
    stmt = select(Milestone).where(Milestone.workspace_id == workspace_id)
    if project:
        stmt = stmt.where(Milestone.project == project)
    rows = (await session.scalars(stmt)).all()
    now = datetime.now(timezone.utc)
    result: list[dict[str, Any]] = []
    for m in rows:
        done, total = await _milestone_progress(session, workspace_id, m.project)
        if m.status not in ("done", "completed") and m.target_date:
            try:
                target = datetime.fromisoformat(m.target_date)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                if target < now:
                    m.status = "overdue"
            except ValueError:
                pass
        result.append({"milestone_id": m.milestone_id, "project": m.project,
                       "title": m.title, "target_date": m.target_date,
                       "description": m.description, "status": m.status,
                       "progress": {"done": done, "total": total}})
    await session.flush()
    return result


async def _milestone_progress(session: AsyncSession, workspace_id: uuid_lib.UUID,
                              project_name: str) -> tuple[int, int]:
    """Count done vs total non-cancelled tasks for a project."""
    proj = await _get_project_by_name(session, workspace_id, project_name)
    if proj is None:
        return 0, 0
    total = await session.scalar(select(func.count(MemoryTask.id)).where(
        MemoryTask.workspace_id == workspace_id, MemoryTask.project_id == proj.id,
        MemoryTask.status != MemoryTaskStatus.CANCELLED)) or 0
    done = await session.scalar(select(func.count(MemoryTask.id)).where(
        MemoryTask.workspace_id == workspace_id, MemoryTask.project_id == proj.id,
        MemoryTask.status == MemoryTaskStatus.DONE)) or 0
    return done, total


async def get_roadmap(
    session: AsyncSession, workspace_id: uuid_lib.UUID, project: str | None = None,
) -> dict[str, Any]:
    """Combine milestones and sprints in chronological order."""
    milestones = await list_milestones(session, workspace_id, project)
    sprints = await list_sprints(session, workspace_id, project)
    items: list[dict[str, Any]] = []
    for m in milestones:
        items.append({"type": "milestone", "date": m["target_date"] or "", **m})
    for s in sprints:
        items.append({"type": "sprint", "date": s["start_date"] or "", **s})
    items.sort(key=lambda x: x["date"])
    return {"project": project, "items": items}


async def capacity_forecast(
    session: AsyncSession, workspace_id: uuid_lib.UUID,
    project: str | None = None, weeks: int = 2,
) -> dict[str, Any]:
    """Forecast capacity vs estimated work. Warns if overcommitted (>80%)."""
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == workspace_id))).all()
    if project:
        proj = await _get_project_by_name(session, workspace_id, project)
        task_rows = ((await session.scalars(select(MemoryTask).where(
            MemoryTask.workspace_id == workspace_id, MemoryTask.project_id == proj.id,
            MemoryTask.status.in_(_OPEN))).all()) if proj else [])
    else:
        task_rows = (await session.scalars(select(MemoryTask).where(
            MemoryTask.workspace_id == workspace_id,
            MemoryTask.status.in_(_OPEN)))).all()

    per_person: list[dict[str, Any]] = []
    total_cap = 0.0
    total_est = 0.0
    for p in people:
        cap = (p.availability_hours_per_week or 0) * weeks
        total_cap += cap
        p_tasks = [t for t in task_rows if t.assignee_person_id == p.id]
        est = sum((t.estimated_days or 0) for t in p_tasks) * HOURS_PER_DAY
        total_est += est
        util = est / cap if cap > 0 else 0.0
        per_person.append({"name": p.name, "role": p.role.value,
                           "capacity_hours": round(cap, 1),
                           "estimated_hours": round(est, 1),
                           "utilization": round(util, 2),
                           "overcommitted": util > OVERCOMMIT_THRESHOLD})

    unassigned_est = sum((t.estimated_days or 0) for t in task_rows
                         if t.assignee_person_id is None) * HOURS_PER_DAY
    total_est += unassigned_est
    overall = total_est / total_cap if total_cap > 0 else 0.0
    overcommitted = overall > OVERCOMMIT_THRESHOLD

    deferrals: list[dict[str, Any]] = []
    for pp in per_person:
        if not pp["overcommitted"]:
            continue
        person = next(p for p in people if p.name == pp["name"])
        p_tasks = sorted([t for t in task_rows if t.assignee_person_id == person.id],
                         key=lambda t: t.estimated_days or 0, reverse=True)
        remaining = pp["estimated_hours"]
        threshold = pp["capacity_hours"] * OVERCOMMIT_THRESHOLD
        for t in p_tasks:
            if remaining <= threshold:
                break
            task_est = (t.estimated_days or 0) * HOURS_PER_DAY
            deferrals.append({"task_id": str(t.id), "title": t.title,
                              "assignee": pp["name"], "estimated_hours": task_est,
                              "reason": "overcommitted — defer to reduce utilization"})
            remaining -= task_est

    warning = ""
    if overcommitted:
        warning = (f"Team is overcommitted at {overall:.0%} utilization "
                   f"(threshold {OVERCOMMIT_THRESHOLD:.0%}). "
                   f"Consider deferring {len(deferrals)} task(s).")
    return {"total_capacity_hours": round(total_cap, 1),
            "total_estimated_hours": round(total_est, 1),
            "utilization": round(overall, 2), "overcommitted": overcommitted,
            "per_person": per_person, "suggested_deferrals": deferrals,
            "warning": warning}


async def _get_project_by_name(session: AsyncSession, workspace_id: uuid_lib.UUID,
                               name: str) -> Project | None:
    """Find a Project row by name (case-insensitive)."""
    return await session.scalar(select(Project).where(
        Project.workspace_id == workspace_id, func.lower(Project.name) == name.lower()))
