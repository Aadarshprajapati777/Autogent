from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.memory import DecisionHistory


async def store_decision(
    session: AsyncSession, workspace_id: uuid.UUID, decision: dict[str, Any]
) -> str:
    now = datetime.now(timezone.utc)
    decision_id = hashlib.sha256(
        f"{decision.get('query', '')}:{now}".encode()
    ).hexdigest()[:16]

    row = DecisionHistory(
        workspace_id=workspace_id,
        decision_id=decision_id,
        query=decision.get("query", ""),
        audience=decision.get("audience", ""),
        response_text=decision.get("response_text", ""),
        reasoning=decision.get("reasoning", ""),
        risk_level=decision.get("risk_level", ""),
        confidence=float(decision.get("confidence", 0.0) or 0.0),
        suggested_actions=decision.get("suggested_actions", []) or [],
        outcome=decision.get("outcome"),
        outcome_notes=decision.get("outcome_notes"),
        outcome_at=decision.get("outcome_at"),
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return decision_id


async def record_outcome(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    decision_id: str,
    outcome: str,
    notes: str = "",
) -> dict[str, Any] | None:
    stmt = select(DecisionHistory).where(
        DecisionHistory.workspace_id == workspace_id,
        DecisionHistory.decision_id == decision_id,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None

    now = datetime.now(timezone.utc)
    row.outcome = outcome
    row.outcome_notes = notes
    row.outcome_at = now
    await session.flush()
    return {
        "decision_id": row.decision_id,
        "outcome": row.outcome,
        "outcome_notes": row.outcome_notes,
        "outcome_at": row.outcome_at,
    }


async def list_decisions(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    limit: int = 50,
    with_outcome_only: bool = False,
) -> list[dict[str, Any]]:
    stmt = select(DecisionHistory).where(
        DecisionHistory.workspace_id == workspace_id
    )
    if with_outcome_only:
        stmt = stmt.where(DecisionHistory.outcome.isnot(None))
    stmt = stmt.order_by(desc(DecisionHistory.created_at)).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "decision_id": r.decision_id,
            "query": r.query,
            "audience": r.audience,
            "response_text": r.response_text,
            "reasoning": r.reasoning,
            "risk_level": r.risk_level,
            "confidence": r.confidence,
            "suggested_actions": r.suggested_actions,
            "outcome": r.outcome,
            "outcome_notes": r.outcome_notes,
            "outcome_at": r.outcome_at,
            "created_at": r.created_at,
        }
        for r in rows
    ]


async def decision_accuracy(
    session: AsyncSession, workspace_id: uuid.UUID
) -> dict[str, Any]:
    stmt = (
        select(DecisionHistory.outcome, func.count())
        .where(
            DecisionHistory.workspace_id == workspace_id,
            DecisionHistory.outcome.isnot(None),
        )
        .group_by(DecisionHistory.outcome)
    )
    result = await session.execute(stmt)
    outcome_counts: dict[str, int] = {}
    total = 0
    for outcome, count in result.all():
        outcome_counts[outcome] = count
        total += count

    positive = outcome_counts.get("correct", 0) + outcome_counts.get("helped", 0)
    accuracy = (positive / total) if total else 0.0
    return {
        "total_decisions_with_outcomes": total,
        "outcome_counts": outcome_counts,
        "accuracy": accuracy,
    }
