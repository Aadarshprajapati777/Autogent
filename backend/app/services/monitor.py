"""Autonomous risk monitor — ported from CloseLoopAI.

Four detectors over workspace memory generate Alert records: overdue
commitments, engineer silence, single-point-of-failure, stale blockers.
Alerts are deduped by signature; stale open alerts are escalated.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.memory import Alert, Fact, FactKind, FactRelation, TemporalStatus

logger = logging.getLogger(__name__)

SILENCE_THRESHOLD_DAYS = 4
OVERDUE_GRACE_HOURS = 2
BLOCKER_STALE_DAYS = 3
ESCALATION_THRESHOLD_HOURS = 24

_SEVERITY_ORDER = ["low", "medium", "high", "critical"]


def alert_signature(risk: dict[str, Any]) -> str:
    """Deterministic 16-char alert id from the risk's identity fields."""
    raw = f"{risk.get('alert_type')}:{risk.get('subject')}:{risk.get('project')}:{risk.get('person')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def store_alert(session: AsyncSession, workspace_id: Any, risk: dict[str, Any]) -> dict[str, Any] | None:
    """Persist a risk as an Alert unless an open one with the same signature exists."""
    alert_id = alert_signature(risk)
    existing = await session.scalar(
        select(Alert).where(Alert.workspace_id == workspace_id, Alert.alert_id == alert_id, Alert.status == "open")
    )
    if existing:
        return None
    alert = Alert(
        workspace_id=workspace_id, alert_id=alert_id, alert_type=risk.get("alert_type", ""),
        subject=risk.get("subject", "") or "", project=risk.get("project"),
        person=risk.get("person"), severity=risk.get("severity", "medium"),
        message=risk.get("message", ""), evidence_fact_id=risk.get("evidence_fact_id"),
        status="open", escalation_level=0,
    )
    session.add(alert)
    await session.flush()
    return {"alert_id": alert_id, "alert_type": alert.alert_type, "subject": alert.subject,
            "project": alert.project, "person": alert.person, "severity": alert.severity,
            "message": alert.message, "evidence_fact_id": alert.evidence_fact_id, "status": alert.status}


async def list_alerts(session: AsyncSession, workspace_id: Any, status: str = "open", limit: int = 50) -> list[dict[str, Any]]:
    """List alerts for a workspace filtered by status, newest first."""
    stmt = (select(Alert).where(Alert.workspace_id == workspace_id, Alert.status == status)
            .order_by(desc(Alert.created_at)).limit(limit))
    rows = (await session.execute(stmt)).scalars().all()
    return [{"alert_id": r.alert_id, "alert_type": r.alert_type, "subject": r.subject,
             "project": r.project, "person": r.person, "severity": r.severity,
             "message": r.message, "evidence_fact_id": r.evidence_fact_id, "status": r.status,
             "escalation_level": r.escalation_level, "acknowledged_at": r.acknowledged_at,
             "escalated_at": r.escalated_at, "created_at": r.created_at} for r in rows]


async def acknowledge_alert(session: AsyncSession, workspace_id: Any, alert_id: str) -> dict[str, Any] | None:
    """Mark an open alert as acknowledged. Returns details or None."""
    alert = await session.scalar(
        select(Alert).where(Alert.workspace_id == workspace_id, Alert.alert_id == alert_id))
    if not alert or alert.acknowledged_at:
        return None
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.status = "acknowledged"
    await session.flush()
    return {"alert_id": alert.alert_id, "status": alert.status}


async def run_monitor_cycle(session: AsyncSession, workspace_id: Any) -> dict[str, Any]:
    """Run all four detectors in sequence and store resulting alerts."""
    started = time.perf_counter()
    risks: list[dict[str, Any]] = []
    risks.extend(await _find_overdue_commitments(session, workspace_id))
    risks.extend(await _find_silent_engineers(session, workspace_id))
    risks.extend(await _find_single_points_of_failure(session, workspace_id))
    risks.extend(await _find_stale_blockers(session, workspace_id))
    alerts: list[dict[str, Any]] = []
    for risk in risks:
        stored = await store_alert(session, workspace_id, risk)
        if stored:
            alerts.append(stored)
    await session.flush()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {"alerts_generated": len(alerts), "alerts": alerts, "elapsed_ms": elapsed_ms}


async def _fulfilled_fact_ids(session: AsyncSession, workspace_id: Any, fact_ids: list[str]) -> set[str]:
    """Return the subset of fact_ids that have a fulfilled_by relation."""
    if not fact_ids:
        return set()
    rows = (await session.execute(
        select(FactRelation.from_fact_id).where(
            FactRelation.workspace_id == workspace_id,
            FactRelation.relation_type == "fulfilled_by",
            FactRelation.from_fact_id.in_(fact_ids)))).scalars().all()
    return set(rows)


async def _find_overdue_commitments(session: AsyncSession, workspace_id: Any) -> list[dict[str, Any]]:
    """COMMITMENT facts that are CURRENT, past due (plus grace), no FULFILLED_BY."""
    grace = datetime.now(timezone.utc) - timedelta(hours=OVERDUE_GRACE_HOURS)
    stmt = select(Fact).where(
        Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.COMMITMENT,
        Fact.temporal_status == TemporalStatus.CURRENT, Fact.due_date.is_not(None))
    facts = (await session.execute(stmt)).scalars().all()
    if not facts:
        return []
    fulfilled = await _fulfilled_fact_ids(session, workspace_id, [f.fact_id for f in facts])
    risks: list[dict[str, Any]] = []
    for f in facts:
        if f.fact_id in fulfilled:
            continue
        try:
            due = datetime.fromisoformat(f.due_date)  # type: ignore[arg-type]
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if due >= grace:
            continue
        risks.append({"alert_type": "overdue_commitment", "subject": f.subject, "project": f.project,
                      "person": f.speaker, "severity": "high",
                      "message": f"Commitment '{f.subject}' is overdue (due {f.due_date}).",
                      "evidence_fact_id": f.fact_id})
    return risks


async def _find_silent_engineers(session: AsyncSession, workspace_id: Any) -> list[dict[str, Any]]:
    """People with open commitments who have produced no fact in SILENCE_THRESHOLD_DAYS."""
    silence_cutoff = datetime.now(timezone.utc) - timedelta(days=SILENCE_THRESHOLD_DAYS)
    comm_stmt = select(Fact).where(
        Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.COMMITMENT,
        Fact.temporal_status == TemporalStatus.CURRENT, Fact.speaker.is_not(None))
    commitments = (await session.execute(comm_stmt)).scalars().all()
    if not commitments:
        return []
    fulfilled = await _fulfilled_fact_ids(session, workspace_id, [f.fact_id for f in commitments])
    open_speakers = {f.speaker for f in commitments if f.fact_id not in fulfilled and f.speaker}
    if not open_speakers:
        return []
    recent_stmt = (select(Fact.speaker).where(
        Fact.workspace_id == workspace_id, Fact.speaker.in_(open_speakers),
        Fact.created_at >= silence_cutoff).distinct())
    recent_speakers = set((await session.execute(recent_stmt)).scalars().all())
    risks: list[dict[str, Any]] = []
    for name in open_speakers - recent_speakers:
        evidence = next((f for f in commitments if f.speaker == name and f.fact_id not in fulfilled), None)
        risks.append({"alert_type": "engineer_silence", "subject": name,
                      "project": evidence.project if evidence else None, "person": name,
                      "severity": "medium",
                      "message": f"{name} has open commitments but no activity in {SILENCE_THRESHOLD_DAYS} days.",
                      "evidence_fact_id": evidence.fact_id if evidence else None})
    return risks


async def _find_single_points_of_failure(session: AsyncSession, workspace_id: Any) -> list[dict[str, Any]]:
    """Projects where all open commitments belong to a single engineer."""
    comm_stmt = select(Fact).where(
        Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.COMMITMENT,
        Fact.temporal_status == TemporalStatus.CURRENT,
        Fact.project.is_not(None), Fact.speaker.is_not(None))
    commitments = (await session.execute(comm_stmt)).scalars().all()
    if not commitments:
        return []
    fulfilled = await _fulfilled_fact_ids(session, workspace_id, [f.fact_id for f in commitments])
    by_project: dict[str, list[Fact]] = {}
    for f in commitments:
        if f.fact_id not in fulfilled:
            by_project.setdefault(f.project, []).append(f)
    risks: list[dict[str, Any]] = []
    for project, facts in by_project.items():
        if len(facts) < 2:
            continue
        speakers = {f.speaker for f in facts if f.speaker}
        if len(speakers) == 1:
            person = next(iter(speakers))
            risks.append({"alert_type": "single_point_of_failure", "subject": project,
                          "project": project, "person": person, "severity": "medium",
                          "message": f"All {len(facts)} open commitments on '{project}' belong to {person} — bus factor of 1.",
                          "evidence_fact_id": facts[0].fact_id})
    return risks


async def _find_stale_blockers(session: AsyncSession, workspace_id: Any) -> list[dict[str, Any]]:
    """BLOCKER facts older than BLOCKER_STALE_DAYS with no status update since."""
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=BLOCKER_STALE_DAYS)
    stmt = select(Fact).where(
        Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.BLOCKER,
        Fact.temporal_status == TemporalStatus.CURRENT, Fact.valid_from < stale_cutoff)
    blockers = (await session.execute(stmt)).scalars().all()
    if not blockers:
        return []
    risks: list[dict[str, Any]] = []
    for b in blockers:
        update_stmt = (select(Fact.fact_id).where(
            Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.STATUS_UPDATE,
            Fact.created_at >= b.valid_from, Fact.subject == b.subject).limit(1))
        if await session.scalar(update_stmt):
            continue
        risks.append({"alert_type": "stale_blocker", "subject": b.subject, "project": b.project,
                      "person": b.speaker, "severity": "high",
                      "message": f"Blocker '{b.subject}' open for over {BLOCKER_STALE_DAYS} days with no status update.",
                      "evidence_fact_id": b.fact_id})
    return risks


async def escalate_stale_alerts(session: AsyncSession, workspace_id: Any) -> dict[str, Any]:
    """Escalate open, unacknowledged alerts older than ESCALATION_THRESHOLD_HOURS."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ESCALATION_THRESHOLD_HOURS)
    stmt = select(Alert).where(
        Alert.workspace_id == workspace_id, Alert.status == "open",
        Alert.acknowledged_at.is_(None), Alert.created_at < cutoff)
    alerts = (await session.execute(stmt)).scalars().all()
    escalated: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for alert in alerts:
        try:
            idx = _SEVERITY_ORDER.index(alert.severity)
        except ValueError:
            idx = 1
        if idx < len(_SEVERITY_ORDER) - 1:
            alert.severity = _SEVERITY_ORDER[idx + 1]
        alert.escalation_level = (alert.escalation_level or 0) + 1
        alert.escalated_at = now
        escalated.append({"alert_id": alert.alert_id, "alert_type": alert.alert_type,
                          "severity": alert.severity, "escalation_level": alert.escalation_level})
    if escalated:
        await session.flush()
    return {"escalated_count": len(escalated), "escalated": escalated}
