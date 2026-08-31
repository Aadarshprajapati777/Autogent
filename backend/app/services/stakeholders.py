"""Stakeholder communication and budget/burn-rate tracking. Ports CloseLoopAI's
stakeholders module: tailored updates per audience (investor/customer/team/board)
and budget vs. spend monitoring with runway estimates. LLM-generated with a
deterministic fallback so the PM always has something to send.
"""
from __future__ import annotations

import logging
import time
import uuid as uuid_lib
from datetime import datetime, timezone

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.llm import LLMError, get_llm
from ..agent.parsing import parse_json_response
from ..agent.prompts import STAKEHOLDER_UPDATE_PROMPT
from ..models.memory import (
    Spend, Fact, FactKind, TemporalStatus, StateSnapshot, Alert, FactRelation, Project,
)

log = logging.getLogger(__name__)
FACT_NAMESPACE = uuid_lib.UUID("7c9e6f5a-2b4d-4f1e-9a3c-8d7b6e5f4a3b")
_VALID_STAKEHOLDERS = {"investor", "customer", "team", "board"}


def _fact_id(subject: str, predicate: str, value: str, topics: list[str]) -> str:
    sig = "|".join([subject.strip().lower(), predicate.strip().lower(),
                    value.strip().lower(), ",".join(sorted(topics))])
    return str(uuid_lib.uuid5(FACT_NAMESPACE, sig))


async def generate_stakeholder_update(
    session: AsyncSession, workspace_id, stakeholder_type: str, project: str | None = None,
) -> dict:
    """Generate a tailored update for a stakeholder audience."""
    started = time.monotonic()
    stakeholder_type = (stakeholder_type or "").strip().lower()
    if stakeholder_type not in _VALID_STAKEHOLDERS:
        stakeholder_type = "team"
    try:
        project_states = await _gather_project_states(session, workspace_id, project)
        person_states = await _gather_person_states(session, workspace_id)
        wins = await _gather_recent_wins(session, workspace_id)
        risks = await _gather_active_risks(session, workspace_id, project)
        budget = await _aggregate_budget(session, workspace_id, project)
        metrics = {"project_count": len(project_states), "person_count": len(person_states),
                   "wins_count": len(wins), "open_risks": len(risks)}
        prompt = STAKEHOLDER_UPDATE_PROMPT.format(
            stakeholder_type=stakeholder_type, project_states=project_states or "(none)",
            metrics=metrics, wins=wins or "(none)", risks=risks or "(none)", budget=budget)
        try:
            response = await get_llm().complete(prompt, max_tokens=1200)
            payload = parse_json_response(response)
            if isinstance(payload, dict) and payload.get("update_body"):
                payload.setdefault("stakeholder_type", stakeholder_type)
                payload["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                return payload
        except (LLMError, ValueError) as exc:
            log.warning("Stakeholder update LLM failed: %s", exc)
        return _fallback_update(stakeholder_type, project_states, wins, risks, budget, started)
    except Exception as exc:
        log.exception("Stakeholder update failed: %s", exc)
        return _fallback_update(stakeholder_type, [], [], [], {}, started)


async def set_budget(
    session: AsyncSession, workspace_id, project: str, total_budget: float,
    currency: str = "USD", start_date: str | None = None, end_date: str | None = None,
) -> dict:
    """Store a project budget as a Fact (Project has no budget fields)."""
    try:
        topics = ["budget"]
        value = str(total_budget)
        fid = _fact_id(project, "has_budget", value, topics)
        now = datetime.now(timezone.utc)
        old_rows = (await session.scalars(select(Fact).where(
            Fact.workspace_id == workspace_id, Fact.fact_id == fid,
            Fact.temporal_status == TemporalStatus.CURRENT))).all()
        for old in old_rows:
            old.temporal_status = TemporalStatus.SUPERSEDED
            old.valid_until = now
            old.superseded_by = fid
        session.add(Fact(
            workspace_id=workspace_id, fact_id=fid, subject=project, predicate="has_budget",
            value=value, fact_kind=FactKind.FACT, topics=topics, project=project,
            numeric_value=float(total_budget), unit=currency,
            temporal_status=TemporalStatus.CURRENT, valid_from=now))
        await session.flush()
        return {"project": project, "total_budget": float(total_budget), "currency": currency,
                "start_date": start_date, "end_date": end_date, "fact_id": fid}
    except Exception as exc:
        log.exception("set_budget failed: %s", exc)
        raise


async def record_spend(
    session: AsyncSession, workspace_id, project: str, amount: float,
    category: str = "general", description: str | None = None,
) -> dict:
    """Record a spend against a project budget."""
    try:
        spend = Spend(workspace_id=workspace_id, spend_id=f"spend:{uuid_lib.uuid4().hex[:12]}",
                      project=project, amount=float(amount), currency="USD",
                      category=category, description=description)
        session.add(spend)
        await session.flush()
        return {"spend_id": spend.spend_id, "project": project, "amount": float(amount),
                "currency": spend.currency, "category": category, "description": description}
    except Exception as exc:
        log.exception("record_spend failed: %s", exc)
        raise


async def get_budget_status(session: AsyncSession, workspace_id, project: str | None = None) -> dict:
    """Get budget vs. spend status with runway and warning level."""
    try:
        return await _aggregate_budget(session, workspace_id, project)
    except Exception as exc:
        log.exception("get_budget_status failed: %s", exc)
        raise


# --- Helpers ----------------------------------------------------------------

async def _gather_project_states(session: AsyncSession, workspace_id, project: str | None) -> list[dict]:
    stmt = select(StateSnapshot).where(
        StateSnapshot.workspace_id == workspace_id, StateSnapshot.entity_type == "project")
    if project:
        stmt = stmt.where(StateSnapshot.entity_name == project)
    rows = (await session.scalars(stmt.order_by(desc(StateSnapshot.created_at)).limit(20))).all()
    return [{"name": r.entity_name, "state": r.state, "score": r.score,
             "summary": r.summary, "risk_signals": r.risk_signals} for r in rows]


async def _gather_person_states(session: AsyncSession, workspace_id) -> list[dict]:
    stmt = select(StateSnapshot).where(
        StateSnapshot.workspace_id == workspace_id, StateSnapshot.entity_type == "person"
    ).order_by(desc(StateSnapshot.created_at)).limit(20)
    rows = (await session.scalars(stmt)).all()
    return [{"name": r.entity_name, "state": r.state, "score": r.score} for r in rows]


async def _gather_recent_wins(session: AsyncSession, workspace_id) -> list[str]:
    """Recent wins = facts referenced by 'fulfilled_by' relations."""
    rels = (await session.scalars(select(FactRelation).where(
        FactRelation.workspace_id == workspace_id,
        FactRelation.relation_type == "fulfilled_by",
    ).order_by(desc(FactRelation.created_at)).limit(10))).all()
    target_ids = [r.to_fact_id for r in rels if r.to_fact_id]
    if not target_ids:
        return []
    facts = (await session.scalars(select(Fact).where(
        Fact.workspace_id == workspace_id, Fact.fact_id.in_(target_ids)))).all()
    by_id = {f.fact_id: f for f in facts}
    return [f"{by_id[r.to_fact_id].subject}: {by_id[r.to_fact_id].value}"
            for r in rels if r.to_fact_id in by_id]


async def _gather_active_risks(session: AsyncSession, workspace_id, project: str | None) -> list[dict]:
    stmt = select(Alert).where(Alert.workspace_id == workspace_id, Alert.status == "open")
    if project:
        stmt = stmt.where(Alert.project == project)
    rows = (await session.scalars(stmt.order_by(desc(Alert.created_at)).limit(15))).all()
    return [{"type": r.alert_type, "severity": r.severity, "message": r.message,
             "project": r.project} for r in rows]


async def _aggregate_budget(session: AsyncSession, workspace_id, project: str | None) -> dict:
    """Compute total budget, spend, remaining, utilization, runway, warning."""
    bstmt = select(Fact).where(
        Fact.workspace_id == workspace_id, Fact.predicate == "has_budget",
        Fact.temporal_status == TemporalStatus.CURRENT)
    if project:
        bstmt = bstmt.where(Fact.subject == project)
    bfact = await session.scalar(bstmt.order_by(desc(Fact.valid_from)).limit(1))
    total_budget = float(bfact.numeric_value) if bfact and bfact.numeric_value else (
        float(bfact.value) if bfact else 0.0)
    currency = bfact.unit if bfact else "USD"
    budget_project = bfact.subject if bfact else project

    sstmt = select(Spend).where(Spend.workspace_id == workspace_id)
    if budget_project:
        sstmt = sstmt.where(Spend.project == budget_project)
    spends = (await session.scalars(sstmt)).all()

    spent = sum(s.amount for s in spends)
    by_category: dict[str, float] = {}
    first_spend_date: datetime | None = None
    for s in spends:
        by_category[s.category] = by_category.get(s.category, 0.0) + s.amount
        if s.created_at and (first_spend_date is None or s.created_at < first_spend_date):
            first_spend_date = s.created_at

    remaining = total_budget - spent
    utilization_pct = (spent / total_budget * 100.0) if total_budget > 0 else 0.0

    runway_weeks: float | None = None
    now = datetime.now(timezone.utc)
    if first_spend_date and spent > 0 and remaining > 0:
        if first_spend_date.tzinfo is None:
            first_spend_date = first_spend_date.replace(tzinfo=timezone.utc)
        elapsed_days = max(1.0, (now - first_spend_date).total_seconds() / 86400.0)
        burn_per_week = spent / (elapsed_days / 7.0)
        if burn_per_week > 0:
            runway_weeks = round(remaining / burn_per_week, 1)

    if utilization_pct >= 90:
        warning = "CRITICAL"
    elif utilization_pct >= 75:
        warning = "WARNING"
    elif utilization_pct >= 50:
        warning = "halfway"
    else:
        warning = "healthy"
    return {"project": budget_project, "total_budget": round(total_budget, 2),
            "spent": round(spent, 2), "remaining": round(remaining, 2),
            "utilization_pct": round(utilization_pct, 1), "runway_weeks": runway_weeks,
            "spend_count": len(spends),
            "by_category": {k: round(v, 2) for k, v in by_category.items()},
            "warning": warning, "currency": currency}


def _fallback_update(stakeholder_type, project_states, wins, risks, budget, started) -> dict:
    """Deterministic summary when the LLM is unavailable."""
    lines: list[str] = []
    if project_states:
        lines.append(f"Tracking {len(project_states)} project(s).")
        for p in project_states[:3]:
            lines.append(f"- {p['name']}: {p['state']} (score {p.get('score', 0)})")
    else:
        lines.append("No project state available yet.")
    if wins:
        lines.append(f"Recent wins ({len(wins)}): " + "; ".join(wins[:3]))
    if risks:
        lines.append(f"Open risks ({len(risks)}): " + "; ".join(
            r.get("message", "")[:60] for r in risks[:3]))
    if budget and budget.get("total_budget"):
        lines.append(f"Budget: {budget.get('spent', 0)}/{budget.get('total_budget', 0)} "
                     f"({budget.get('utilization_pct', 0)}% used, {budget.get('warning', 'healthy')})")
    asks: list[str] = []
    if budget and budget.get("warning") == "CRITICAL":
        asks.append("Approve additional budget or reduce scope immediately.")
    elif risks:
        asks.append("Review open risks and decide on mitigations.")
    return {"update_title": f"{stakeholder_type.title()} update", "update_body": "\n".join(lines),
            "key_points": lines[:5], "asks": asks, "tone": "cautious" if risks else "confident",
            "stakeholder_type": stakeholder_type,
            "elapsed_ms": int((time.monotonic() - started) * 1000)}
