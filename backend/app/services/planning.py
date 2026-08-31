"""Planning intelligence — scope creep detection, dependency analysis,
estimation accuracy tracking, and task prioritization. Ports CloseLoopAI's
planning module; combines memory graph signals with LLM synthesis."""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.llm import LLMError, get_llm
from ..agent.parsing import parse_json_response
from ..agent.prompts import SCOPE_CREEP_PROMPT
from ..models.memory import (
    Fact, FactKind, FactRelation, MemoryTask, MemoryTaskStatus,
    Person, Project, TemporalStatus,
)

log = logging.getLogger(__name__)
SCOPE_SETTLE_DAYS = 7


def _days_ago(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _parse_date(value: str | None) -> datetime | None:
    """Best-effort parse of a loose date string (YYYY-MM-DD or ISO)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except (ValueError, TypeError):
        return None


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


async def detect_scope_creep(
    session: AsyncSession, workspace_id: uuid.UUID, project_name: str,
) -> dict[str, Any]:
    """Compare original requirements to additions after the first 7 days. Uses
    SCOPE_CREEP_PROMPT with LLM; falls back to deterministic creep rule."""
    started = datetime.now(timezone.utc)
    try:
        reqs = (await session.scalars(
            select(Fact).where(
                Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.REQUIREMENT,
                Fact.temporal_status == TemporalStatus.CURRENT,
                func.lower(Fact.project) == project_name.lower(),
            ).order_by(Fact.valid_from.asc())
        )).all()
        if not reqs:
            return _creep_result(False, 0, 0, [], started)
        first_date = _aware(reqs[0].valid_from) or _days_ago(SCOPE_SETTLE_DAYS)
        settle_cutoff = first_date + timedelta(days=SCOPE_SETTLE_DAYS)
        original = [r for r in reqs if (_aware(r.valid_from) or first_date) <= settle_cutoff]
        added = [r for r in reqs if (_aware(r.valid_from) or first_date) > settle_cutoff]
        project = await session.scalar(
            select(Project).where(
                Project.workspace_id == workspace_id, func.lower(Project.name) == project_name.lower(),
            )
        )
        task_count = await session.scalar(
            select(func.count(MemoryTask.id)).where(
                MemoryTask.workspace_id == workspace_id,
                MemoryTask.project_id == project.id if project else None,
            )
        ) or 0
        original_items = [r.value for r in original]
        added_items = [r.value for r in added]
        llm_result = await _llm_scope_creep(
            project_name, original_items, added_items, first_date.date().isoformat(),
            project.deadline if project else None, task_count,
        )
        if llm_result:
            llm_result["elapsed_ms"] = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            return llm_result
        creep = len(added) > 3 or (len(original) and len(added) / max(1, len(original)) > 0.3)
        return _creep_result(creep, len(original), len(added), added_items, started)
    except Exception as exc:  # noqa: BLE001
        log.warning("detect_scope_creep failed for %s: %s", project_name, exc)
        return _creep_result(False, 0, 0, [], started)


def _creep_result(
    detected: bool, original: int, added: int, additions: list[str], started: datetime,
) -> dict[str, Any]:
    return {
        "scope_creep_detected": detected, "original_scope_items": original, "added_items": added,
        "additions": additions,
        "impact_assessment": "deterministic fallback" if original else "no requirements found",
        "recommendation": "review additions" if detected else "no action needed",
        "founder_message": (
            f"Scope has grown by {added} items beyond the original {original}. "
            "Consider cutting or extending the timeline." if detected else "Scope looks stable."
        ),
        "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    }


async def _llm_scope_creep(
    project: str, original: list[str], added: list[str],
    start_date: str, deadline: str | None, task_count: int,
) -> dict[str, Any] | None:
    prompt = SCOPE_CREEP_PROMPT.format(
        project=project,
        original_scope="\n".join(f"- {o}" for o in original) or "(none)",
        additions="\n".join(f"- {a}" for a in added) or "(none)",
        start_date=start_date, deadline=deadline or "not set", task_count=task_count,
    )
    try:
        response = await get_llm().complete(prompt, max_tokens=800)
        payload = parse_json_response(response)
        if isinstance(payload, dict):
            return payload
    except (LLMError, ValueError) as exc:
        log.warning("Scope creep LLM failed for %s: %s", project, exc)
    return None


async def analyze_dependencies(
    session: AsyncSession, workspace_id: uuid.UUID, project_name: str | None = None,
) -> dict[str, Any]:
    """Analyze dependency graph from FactRelation (blocks/depends_on) plus
    MemoryTask blockers. Finds unresolved blockers, chains, critical path
    (longest chain), and downstream risks (overdue blockers)."""
    try:
        rels = (await session.scalars(
            select(FactRelation).where(
                FactRelation.workspace_id == workspace_id,
                FactRelation.relation_type.in_(["blocks", "depends_on"]),
            )
        )).all()
        fact_ids = {r.from_fact_id for r in rels} | {r.to_fact_id for r in rels}
        facts_by_id: dict[str, Fact] = {}
        if fact_ids:
            facts = (await session.scalars(
                select(Fact).where(Fact.workspace_id == workspace_id, Fact.fact_id.in_(list(fact_ids)))
            )).all()
            facts_by_id = {f.fact_id: f for f in facts}
        dependencies: list[dict[str, Any]] = []
        for rel in rels:
            src = facts_by_id.get(rel.from_fact_id)
            dst = facts_by_id.get(rel.to_fact_id)
            if project_name and src and src.project and src.project.lower() != project_name.lower():
                continue
            dependencies.append({
                "from_fact_id": rel.from_fact_id, "to_fact_id": rel.to_fact_id,
                "relation_type": rel.relation_type,
                "from_subject": src.subject if src else None, "from_value": src.value if src else None,
                "to_subject": dst.subject if dst else None, "to_value": dst.value if dst else None,
                "from_kind": src.fact_kind.value if src else None, "to_kind": dst.fact_kind.value if dst else None,
                "resolved": (src.temporal_status != TemporalStatus.CURRENT if src else True),
            })
        blocked_tasks = (await session.scalars(
            select(MemoryTask).where(
                MemoryTask.workspace_id == workspace_id, MemoryTask.status == MemoryTaskStatus.BLOCKED,
            )
        )).all()
        for task in blocked_tasks:
            dependencies.append({
                "from_fact_id": task.source_fact_id, "to_fact_id": None, "relation_type": "blocks",
                "from_subject": task.title, "from_value": "blocked task", "to_subject": None, "to_value": None,
                "from_kind": "task", "to_kind": None, "resolved": False,
            })
        unresolved_blockers = [d for d in dependencies if d["relation_type"] == "blocks" and not d["resolved"]]
        chains = _build_chains(dependencies)
        critical_path = max(chains, key=len) if chains else []
        now = datetime.now(timezone.utc)
        downstream_risks = []
        for d in unresolved_blockers:
            src = facts_by_id.get(d["from_fact_id"])
            if src and src.due_date:
                due = _parse_date(src.due_date)
                if due and due < now:
                    downstream_risks.append({
                        "blocker": d["from_subject"], "due_date": src.due_date, "days_overdue": (now - due).days,
                    })
        return {
            "total_dependencies": len(dependencies), "unresolved_blockers": len(unresolved_blockers),
            "dependencies": dependencies, "dependency_chains": chains, "critical_path": critical_path,
            "downstream_risks": downstream_risks, "has_risks": bool(unresolved_blockers or downstream_risks),
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("analyze_dependencies failed: %s", exc)
        return {"total_dependencies": 0, "unresolved_blockers": 0, "dependencies": [],
                "dependency_chains": [], "critical_path": [], "downstream_risks": [], "has_risks": False}


def _build_chains(dependencies: list[dict[str, Any]]) -> list[list[str]]:
    """Build dependency chains from a flat edge list (root-to-leaf hops)."""
    children: dict[str, list[str]] = defaultdict(list)
    nodes: set[str] = set()
    for d in dependencies:
        src = d.get("from_fact_id") or d.get("from_subject")
        dst = d.get("to_fact_id") or d.get("to_subject")
        if src and dst:
            children[src].append(dst); nodes.add(src); nodes.add(dst)
    roots = {n for n in nodes if not any(n in kids for kids in children.values())} or nodes
    chains: list[list[str]] = []
    def walk(node: str, path: list[str]) -> None:
        kids = children.get(node, [])
        if not kids:
            chains.append(path + [node]); return
        for kid in kids:
            if kid in path:  # cycle guard
                chains.append(path + [node]); continue
            walk(kid, path + [node])

    for root in roots:
        walk(root, [])
    return chains


async def estimation_accuracy(
    session: AsyncSession, workspace_id: uuid.UUID, person: str | None = None,
) -> dict[str, Any]:
    """Track estimated vs actual days for completed MemoryTasks. Uses
    STATUS_UPDATE facts for actual completion dates. Per-person calibration:
    ratio = actual/estimated (>1.5 underestimates, <0.7 overestimates)."""
    try:
        tasks = (await session.scalars(
            select(MemoryTask).where(
                MemoryTask.workspace_id == workspace_id, MemoryTask.status == MemoryTaskStatus.DONE,
                MemoryTask.estimated_days.isnot(None),
            )
        )).all()
        person_ids = {t.assignee_person_id for t in tasks if t.assignee_person_id}
        people: dict[uuid.UUID, str] = {}
        if person_ids:
            rows = (await session.scalars(select(Person).where(Person.id.in_(list(person_ids))))).all()
            people = {p.id: p.name for p in rows}
        status_facts = (await session.scalars(
            select(Fact).where(
                Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.STATUS_UPDATE,
                Fact.temporal_status == TemporalStatus.CURRENT,
            ).order_by(Fact.valid_from.asc())
        )).all()
        completion_by_subject: dict[str, datetime] = {}
        for f in status_facts:
            key = (f.subject or "").lower()
            if key and key not in completion_by_subject:
                completion_by_subject[key] = _aware(f.valid_from) or datetime.now(timezone.utc)
        tasks_out: list[dict[str, Any]] = []
        per_person: dict[str, list[float]] = defaultdict(list)
        ratios: list[float] = []
        for task in tasks:
            est = task.estimated_days or 0
            completed_at = completion_by_subject.get((task.title or "").lower())
            actual = ratio = None
            if completed_at and task.created_at:
                created = _aware(task.created_at)
                if created:
                    actual = max(0.5, (completed_at - created).days)
                    if est > 0:
                        ratio = round(actual / est, 2); ratios.append(ratio)
            assignee_name = people.get(task.assignee_person_id) if task.assignee_person_id else None
            if person and (assignee_name or "").lower() != person.lower():
                continue
            if ratio is not None and assignee_name:
                per_person[assignee_name].append(ratio)
            tasks_out.append({
                "title": task.title, "estimated_days": est, "actual_days": actual, "ratio": ratio,
                "assignee": assignee_name, "completed_at": completed_at.isoformat() if completed_at else None,
            })
        overall = round(sum(ratios) / len(ratios), 2) if ratios else None
        tendency = ("underestimates" if overall and overall > 1.5
                    else "overestimates" if overall and overall < 0.7
                    else "calibrated" if overall else "unknown")
        calibration = {}
        for name, rs in per_person.items():
            avg = round(sum(rs) / len(rs), 2)
            calibration[name] = {
                "avg_ratio": avg,
                "tendency": "underestimates" if avg > 1.5 else "overestimates" if avg < 0.7 else "calibrated",
                "sample_size": len(rs),
            }
        return {"total_completed": len(tasks), "with_actuals": len(ratios), "overall_avg_ratio": overall,
                "overall_tendency": tendency, "per_person_calibration": calibration, "tasks": tasks_out}
    except Exception as exc:  # noqa: BLE001
        log.warning("estimation_accuracy failed: %s", exc)
        return {"total_completed": 0, "with_actuals": 0, "overall_avg_ratio": None,
                "overall_tendency": "unknown", "per_person_calibration": {}, "tasks": []}


async def prioritize_tasks(
    session: AsyncSession, workspace_id: uuid.UUID, project_name: str | None = None,
) -> dict[str, Any]:
    """Rank open MemoryTasks by urgency, dependency, critical path, quick win, assignment. Returns sorted list with scores."""
    try:
        project = None
        if project_name:
            project = await session.scalar(
                select(Project).where(
                    Project.workspace_id == workspace_id, func.lower(Project.name) == project_name.lower(),
                )
            )
        query = select(MemoryTask).where(
            MemoryTask.workspace_id == workspace_id,
            MemoryTask.status.in_([MemoryTaskStatus.OPEN, MemoryTaskStatus.IN_PROGRESS, MemoryTaskStatus.BLOCKED]),
        )
        if project:
            query = query.where(MemoryTask.project_id == project.id)
        tasks = (await session.scalars(query)).all()
        if not tasks:
            return {"total_open_tasks": 0, "prioritized": [], "top_priority": None, "recommended_order": []}
        deps = await analyze_dependencies(session, workspace_id, project_name)
        critical_nodes: set[str] = set()
        for chain in deps.get("dependency_chains", []):
            critical_nodes.update(chain)
        blocking_ids = {d["from_fact_id"] for d in deps.get("dependencies", [])
                        if d.get("relation_type") == "blocks" and not d.get("resolved")}
        now = datetime.now(timezone.utc)
        scored: list[dict[str, Any]] = []
        for task in tasks:
            score = 0; reasons: list[str] = []
            due = _parse_date(task.deadline)
            if due:
                days_left = (due - now).days
                if days_left < 0: score += 30; reasons.append("overdue")
                elif days_left < 7: score += 20; reasons.append("due<7d")
                elif days_left < 14: score += 10; reasons.append("due<14d")
            if task.source_fact_id and task.source_fact_id in blocking_ids:
                score += 15; reasons.append("blocks others")
            if task.source_fact_id and task.source_fact_id in critical_nodes:
                score += 10; reasons.append("critical path")
            if task.estimated_days is not None and task.estimated_days <= 1:
                score += 5; reasons.append("quick win")
            if task.assignee_person_id:
                score += 3; reasons.append("assigned")
            scored.append({
                "task_id": str(task.id), "title": task.title, "status": task.status.value,
                "deadline": task.deadline, "estimated_days": task.estimated_days,
                "assignee_person_id": str(task.assignee_person_id) if task.assignee_person_id else None,
                "score": score, "reasons": reasons,
            })
        scored.sort(key=lambda t: t["score"], reverse=True)
        return {"total_open_tasks": len(scored), "prioritized": scored,
                "top_priority": scored[0] if scored else None, "recommended_order": [t["title"] for t in scored]}
    except Exception as exc:  # noqa: BLE001
        log.warning("prioritize_tasks failed: %s", exc)
        return {"total_open_tasks": 0, "prioritized": [], "top_priority": None, "recommended_order": []}
