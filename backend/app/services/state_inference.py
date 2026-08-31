"""State inference — derives the true health of projects and credibility of
people from their facts. Combines deterministic signals (overdue commitments,
unresolved blockers, silence periods) with LLM synthesis for a nuanced
assessment that doesn't take engineer claims at face value.

Replaces kgmemory's /pm/infer-state endpoint. Stores results as StateSnapshot
rows so the PM always has a current view without re-deriving from scratch.
"""
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
from ..agent.prompts import PERSON_STATE_PROMPT, PROJECT_STATE_PROMPT
from ..models.memory import Fact, FactKind, Person, StateSnapshot, TemporalStatus

log = logging.getLogger(__name__)
SINCE_WINDOW_DAYS = 14


async def infer_and_snapshot_state(
    session: AsyncSession, workspace_id: uuid.UUID
) -> dict[str, Any]:
    """Derive project + person state from recent facts, store durable snapshots.
    Called after each ingest cycle (fire-and-forget) so the PM's model of
    reality stays in sync."""
    project_signals = await _collect_project_signals(session, workspace_id)
    person_signals = await _collect_person_signals(session, workspace_id)

    project_states = []
    for name, signals in project_signals.items():
        state = await _infer_project_state(session, workspace_id, name, signals)
        project_states.append(state)
        await _store_snapshot(session, workspace_id, state)

    person_states = []
    for name, signals in person_signals.items():
        state = await _infer_person_state(session, workspace_id, name, signals)
        person_states.append(state)
        await _store_snapshot(session, workspace_id, state)

    await session.flush()
    log.info(
        "State inference for workspace %s: %d projects, %d people",
        workspace_id, len(project_states), len(person_states),
    )
    return {"projects": project_states, "people": person_states}


async def get_latest_states(
    session: AsyncSession, workspace_id: uuid.UUID
) -> dict[str, list[dict]]:
    """Get the most recent state snapshots for a workspace."""
    rows = (await session.scalars(
        select(StateSnapshot)
        .where(StateSnapshot.workspace_id == workspace_id)
        .order_by(StateSnapshot.created_at.desc())
    )).all()

    # Keep only the latest per entity
    seen: dict[str, dict] = {}
    for row in rows:
        key = f"{row.entity_type}:{row.entity_name}"
        if key not in seen:
            seen[key] = {
                "entity_type": row.entity_type,
                "entity_name": row.entity_name,
                "state": row.state,
                "score": row.score,
                "risk_signals": row.risk_signals,
                "summary": row.summary,
                "open_commitments": row.open_commitments,
                "completed_since_last": row.completed_since_last,
                "missed_or_late": row.missed_or_late,
                "days_since_last_seen": row.days_since_last_seen,
            }

    projects = [v for v in seen.values() if v["entity_type"] == "project"]
    people = [v for v in seen.values() if v["entity_type"] == "person"]
    return {"projects": projects, "people": people}


async def _collect_project_signals(
    session: AsyncSession, workspace_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=SINCE_WINDOW_DAYS)
    rows = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            Fact.valid_from >= since,
            Fact.project.isnot(None),
        ).order_by(Fact.valid_from.desc())
    )).all()

    signals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "commitments": [], "completed": [], "missed": [],
            "blockers": [], "engineers": set(), "last_activity": None, "facts": [],
        }
    )
    for fact in rows:
        bucket = signals[fact.project]
        bucket["facts"].append({
            "kind": fact.fact_kind.value, "speaker": fact.speaker,
            "value": fact.value, "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
            "due_date": fact.due_date,
        })
        if fact.fact_kind == FactKind.COMMITMENT:
            bucket["commitments"].append({"speaker": fact.speaker, "value": fact.value, "due_date": fact.due_date})
        elif fact.fact_kind == FactKind.STATUS_UPDATE:
            bucket["completed"].append({"speaker": fact.speaker, "value": fact.value})
        elif fact.fact_kind == FactKind.PERFORMANCE:
            v = (fact.value or "").lower()
            if any(w in v for w in ["missed", "overdue", "late", "failed", "blocked"]):
                bucket["missed"].append({"speaker": fact.speaker, "value": fact.value})
        elif fact.fact_kind == FactKind.BLOCKER:
            bucket["blockers"].append({"speaker": fact.speaker, "value": fact.value})
        if fact.speaker:
            bucket["engineers"].add(fact.speaker)
        if fact.valid_from and (bucket["last_activity"] is None or
                                fact.valid_from > bucket["last_activity"]):
            bucket["last_activity"] = fact.valid_from
    return signals


async def _collect_person_signals(
    session: AsyncSession, workspace_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(days=SINCE_WINDOW_DAYS)
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == workspace_id)
    )).all()

    signals: dict[str, dict[str, Any]] = {}
    for person in people:
        facts = (await session.scalars(
            select(Fact).where(
                Fact.workspace_id == workspace_id,
                Fact.temporal_status == TemporalStatus.CURRENT,
                func.lower(Fact.subject) == person.name.lower(),
                Fact.valid_from >= since,
            ).order_by(Fact.valid_from.desc()).limit(30)
        )).all()

        bucket = {
            "commitments": [], "completed": [], "missed": [],
            "last_seen": None, "facts": [],
        }
        for fact in facts:
            bucket["facts"].append({
                "kind": fact.fact_kind.value, "value": fact.value,
                "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
            })
            if fact.fact_kind == FactKind.COMMITMENT:
                bucket["commitments"].append({"value": fact.value, "due_date": fact.due_date})
            elif fact.fact_kind == FactKind.STATUS_UPDATE:
                bucket["completed"].append({"value": fact.value})
            elif fact.fact_kind == FactKind.PERFORMANCE:
                v = (fact.value or "").lower()
                if any(w in v for w in ["missed", "overdue", "late", "failed", "blocked"]):
                    bucket["missed"].append({"value": fact.value})
            if fact.valid_from and (bucket["last_seen"] is None or
                                    fact.valid_from > bucket["last_seen"]):
                bucket["last_seen"] = fact.valid_from
        signals[person.name] = bucket
    return signals


async def _infer_project_state(
    session: AsyncSession, workspace_id: uuid.UUID,
    project: str, signals: dict[str, Any],
) -> dict[str, Any]:
    deterministic = _deterministic_project_health(signals)
    summary = await _llm_project_summary(project, signals, deterministic)
    return {
        "entity_type": "project",
        "entity_name": project,
        "state": summary.get("health", deterministic["health"]),
        "score": summary.get("health_score", deterministic["health_score"]),
        "open_commitments": len(signals["commitments"]),
        "completed_since_last": len(signals["completed"]),
        "missed_or_late": len(signals["missed"]),
        "risk_signals": summary.get("risk_signals", deterministic["risk_signals"]),
        "summary": summary.get("summary", ""),
        "days_since_last_seen": None,
    }


async def _infer_person_state(
    session: AsyncSession, workspace_id: uuid.UUID,
    person: str, signals: dict[str, Any],
) -> dict[str, Any]:
    deterministic = _deterministic_person_credibility(signals)
    summary = await _llm_person_summary(person, signals, deterministic)
    days_since = _days_since(signals["last_seen"])
    return {
        "entity_type": "person",
        "entity_name": person,
        "state": summary.get("credibility", deterministic["credibility"]),
        "score": summary.get("credibility_score", deterministic["credibility_score"]),
        "open_commitments": len(signals["commitments"]),
        "completed_since_last": len(signals["completed"]),
        "missed_or_late": len(signals["missed"]),
        "risk_signals": summary.get("risk_signals", deterministic["risk_signals"]),
        "summary": summary.get("summary", ""),
        "days_since_last_seen": days_since,
    }


def _deterministic_project_health(signals: dict[str, Any]) -> dict[str, Any]:
    commitments = len(signals["commitments"])
    completed = len(signals["completed"])
    missed = len(signals["missed"])
    blockers = len(signals["blockers"])
    risk_signals: list[str] = []
    if missed >= 2:
        risk_signals.append(f"{missed} performance concerns in last {SINCE_WINDOW_DAYS} days")
    if blockers and not completed:
        risk_signals.append(f"{blockers} open blockers, no completions")
    if commitments > 5 and completed == 0:
        risk_signals.append(f"{commitments} open commitments, none completed")
    if not signals["last_activity"]:
        risk_signals.append("no recent activity")

    score = 0.5 + 0.1 * (completed - missed) - 0.05 * blockers
    score = max(0.0, min(1.0, score))
    if blockers and not completed:
        health = "blocked"
    elif missed >= 2 or score < 0.35:
        health = "delayed"
    elif risk_signals:
        health = "at_risk"
    elif completed and not missed:
        health = "on_track"
    else:
        health = "unknown"
    return {"health": health, "health_score": round(score, 2), "risk_signals": risk_signals}


def _deterministic_person_credibility(signals: dict[str, Any]) -> dict[str, Any]:
    commitments = len(signals["commitments"])
    completed = len(signals["completed"])
    missed = len(signals["missed"])
    total = commitments + completed + missed
    risk_signals: list[str] = []
    if missed >= 2:
        risk_signals.append(f"{missed} missed/flagged in last {SINCE_WINDOW_DAYS} days")
    days = _days_since(signals["last_seen"])
    if days is not None and days >= 5:
        risk_signals.append(f"not seen in {days} days")
    if total == 0:
        score = 0.5
    else:
        score = max(0.0, min(1.0, (completed + 0.5 * commitments - 2 * missed) / total))
    if score >= 0.7:
        credibility = "high"
    elif score >= 0.4:
        credibility = "moderate"
    else:
        credibility = "low"
    return {"credibility": credibility, "credibility_score": round(score, 2), "risk_signals": risk_signals}


def _days_since(last_seen: datetime | None) -> int | None:
    if not last_seen:
        return None
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - last_seen).days)


async def _llm_project_summary(
    project: str, signals: dict[str, Any], deterministic: dict[str, Any],
) -> dict[str, Any]:
    facts_text = _format_signals(signals["facts"][:30])
    prompt = PROJECT_STATE_PROMPT.format(
        project=project,
        deterministic_health=deterministic["health"],
        deterministic_score=deterministic["health_score"],
        risk_signals=", ".join(deterministic["risk_signals"]) or "none",
        facts=facts_text,
    )
    try:
        response = await get_llm().complete(prompt, max_tokens=600)
        payload = parse_json_response(response)
        if isinstance(payload, dict):
            return payload
    except (LLMError, ValueError) as exc:
        log.warning("Project state LLM failed for %s: %s", project, exc)
    return {}


async def _llm_person_summary(
    person: str, signals: dict[str, Any], deterministic: dict[str, Any],
) -> dict[str, Any]:
    facts_text = _format_signals(signals["facts"][:30])
    prompt = PERSON_STATE_PROMPT.format(
        person=person,
        deterministic_credibility=deterministic["credibility"],
        deterministic_score=deterministic["credibility_score"],
        risk_signals=", ".join(deterministic["risk_signals"]) or "none",
        facts=facts_text,
    )
    try:
        response = await get_llm().complete(prompt, max_tokens=500)
        payload = parse_json_response(response)
        if isinstance(payload, dict):
            return payload
    except (LLMError, ValueError) as exc:
        log.warning("Person state LLM failed for %s: %s", person, exc)
    return {}


def _format_signals(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return "(no recent facts)"
    lines = []
    for fact in facts:
        date = (fact.get("valid_from") or "")[:10]
        lines.append(f"- [{date}] {fact.get('kind')}: {fact.get('value')}")
    return "\n".join(lines)


async def _store_snapshot(
    session: AsyncSession, workspace_id: uuid.UUID, state: dict[str, Any],
) -> None:
    snap = StateSnapshot(
        workspace_id=workspace_id,
        entity_type=state["entity_type"],
        entity_name=state["entity_name"],
        state=state["state"],
        score=state["score"],
        risk_signals=state.get("risk_signals") or [],
        summary=state.get("summary"),
        open_commitments=state.get("open_commitments", 0),
        completed_since_last=state.get("completed_since_last", 0),
        missed_or_late=state.get("missed_or_late", 0),
        days_since_last_seen=state.get("days_since_last_seen"),
    )
    session.add(snap)
