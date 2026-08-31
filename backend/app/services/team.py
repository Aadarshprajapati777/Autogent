"""Team intelligence — performance feedback and morale sensing. Ports CloseLoopAI's team module."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.llm import LLMError, get_llm
from ..agent.parsing import parse_json_response
from ..agent.prompts import MORALE_SENSING_PROMPT, PERFORMANCE_FEEDBACK_PROMPT
from ..models.memory import (
    DecisionHistory, Fact, FactKind, FactRelation, Person,
    StateSnapshot, TemporalStatus,
)

log = logging.getLogger(__name__)
MORALE_WINDOW_DAYS = 14
SILENCE_WINDOW_DAYS = 7


def _days_ago(days: int) -> str:
    """ISO 8601 timestamp for `days` days before now (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _fallback_rating(score: float) -> str:
    if score >= 0.7: return "exceeding"
    if score < 0.3: return "concerning"
    if score < 0.5: return "below"
    return "meeting"


def _fallback_morale(avg_neg: float) -> tuple[str, float]:
    if avg_neg > 40: return "concerning", 0.2
    if avg_neg > 25: return "declining", 0.4
    if avg_neg > 10: return "stable", 0.65
    return "high", 0.85


def _fb_fallback(name: str, start: float) -> dict[str, Any]:
    return {"feedback_summary": f"Unable to generate feedback for {name}.",
            "strengths": [], "areas_for_growth": [], "overall_rating": "meeting",
            "message_to_engineer": "", "engineer": name, "reliability_score": 0.5,
            "fulfilled_commitments": 0, "missed_commitments": 0,
            "elapsed_ms": int((time.monotonic() - start) * 1000)}


async def generate_performance_feedback(
    session: AsyncSession, workspace_id: Any, engineer_name: str,
) -> dict[str, Any]:
    """Generate honest, specific performance feedback for an engineer."""
    start = time.monotonic()
    name_lc = engineer_name.lower()
    try:
        person = await session.scalar(select(Person).where(
            Person.workspace_id == workspace_id, func.lower(Person.name) == name_lc))
        if not person:
            return _fb_fallback(engineer_name, start)

        since = datetime.now(timezone.utc) - timedelta(days=MORALE_WINDOW_DAYS)
        cur = TemporalStatus.CURRENT

        # Contribution counts by fact kind
        kind_counts: dict[str, int] = defaultdict(int)
        for kind, cnt in (await session.execute(
            select(Fact.fact_kind, func.count()).where(
                Fact.workspace_id == workspace_id, Fact.temporal_status == cur,
                func.lower(Fact.subject) == name_lc, Fact.valid_from >= since,
            ).group_by(Fact.fact_kind)
        )).all():
            kind_counts[kind.value if hasattr(kind, "value") else str(kind)] = cnt

        # Fulfilled commitments via FactRelation (from_fact is this engineer's commitment)
        fulfilled = int(await session.scalar(
            select(func.count(FactRelation.id)).join(Fact, and_(
                Fact.workspace_id == workspace_id, Fact.fact_id == FactRelation.from_fact_id,
                Fact.temporal_status == cur, func.lower(Fact.subject) == name_lc,
            )).where(FactRelation.workspace_id == workspace_id,
                     FactRelation.relation_type == "fulfilled_by")
        ) or 0)

        # Missed commitments: overdue, current, not fulfilled
        commitment_ids = list((await session.scalars(
            select(Fact.fact_id).where(
                Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.COMMITMENT,
                Fact.temporal_status == cur, func.lower(Fact.subject) == name_lc,
            ))).all())
        fulfilled_ids = set((await session.scalars(
            select(FactRelation.from_fact_id).where(
                FactRelation.workspace_id == workspace_id,
                FactRelation.relation_type == "fulfilled_by",
                FactRelation.from_fact_id.in_(commitment_ids),
            ))).all()) if commitment_ids else set()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        missed = 0
        if commitment_ids:
            conds = [Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.COMMITMENT,
                     Fact.temporal_status == cur, func.lower(Fact.subject) == name_lc,
                     Fact.due_date.isnot(None), Fact.due_date < now_iso]
            if fulfilled_ids:
                conds.append(Fact.fact_id.notin_(list(fulfilled_ids)))
            missed = int(await session.scalar(select(func.count(Fact.id)).where(*conds)) or 0)

        # Reliability from latest person StateSnapshot
        snap = await session.scalar(select(StateSnapshot).where(
            StateSnapshot.workspace_id == workspace_id, StateSnapshot.entity_type == "person",
            StateSnapshot.entity_name == person.name,
        ).order_by(StateSnapshot.created_at.desc()).limit(1))
        reliability_score = float(snap.score) if snap and snap.score is not None else 0.5

        # Recent DecisionHistory entries mentioning the engineer
        like = f"%{engineer_name}%"
        decisions = (await session.scalars(select(DecisionHistory).where(
            DecisionHistory.workspace_id == workspace_id,
            (DecisionHistory.query.ilike(like)) | (DecisionHistory.response_text.ilike(like)),
        ).order_by(desc(DecisionHistory.created_at)).limit(5))).all()
        reviews = [{"query": d.query, "response": d.response_text[:300]} for d in decisions]

        fallback = _fallback_rating(reliability_score)
        prompt = PERFORMANCE_FEEDBACK_PROMPT.format(
            engineer=engineer_name, contributions=dict(kind_counts),
            reliability=round(reliability_score, 2), fulfilled=fulfilled,
            missed=missed, reviews=reviews, skills=person.skills or [])
        result: dict[str, Any] = {}
        try:
            payload = parse_json_response(await get_llm().complete(prompt, max_tokens=600))
            if isinstance(payload, dict):
                result = payload
        except (LLMError, ValueError) as exc:
            log.warning("Performance feedback LLM failed for %s: %s", engineer_name, exc)

        return {
            "feedback_summary": result.get("feedback_summary",
                f"{engineer_name} has a reliability score of {reliability_score:.2f}."),
            "strengths": result.get("strengths", []),
            "areas_for_growth": result.get("areas_for_growth", []),
            "overall_rating": result.get("overall_rating", fallback),
            "message_to_engineer": result.get("message_to_engineer", ""),
            "engineer": engineer_name, "reliability_score": round(reliability_score, 2),
            "fulfilled_commitments": fulfilled, "missed_commitments": missed,
            "elapsed_ms": int((time.monotonic() - start) * 1000)}
    except Exception:
        log.exception("generate_performance_feedback failed for %s", engineer_name)
        return _fb_fallback(engineer_name, start)


async def sense_team_morale(
    session: AsyncSession, workspace_id: Any,
) -> dict[str, Any]:
    """Sense team morale from sentiment patterns across the last 14 days."""
    start = time.monotonic()
    try:
        people = (await session.scalars(
            select(Person).where(Person.workspace_id == workspace_id))).all()
        since_14 = datetime.now(timezone.utc) - timedelta(days=MORALE_WINDOW_DAYS)
        since_7 = datetime.now(timezone.utc) - timedelta(days=SILENCE_WINDOW_DAYS)
        cur = TemporalStatus.CURRENT

        sentiment_data: list[dict[str, Any]] = []
        negative_pcts: list[float] = []
        silent_people: list[str] = []

        for person in people:
            pl = person.name.lower()
            facts = (await session.scalars(select(Fact).where(
                Fact.workspace_id == workspace_id, Fact.temporal_status == cur,
                func.lower(Fact.subject) == pl, Fact.valid_from >= since_14,
            ))).all()
            total = len(facts)
            recent_7 = int(await session.scalar(select(func.count(Fact.id)).where(
                Fact.workspace_id == workspace_id, Fact.temporal_status == cur,
                func.lower(Fact.subject) == pl, Fact.valid_from >= since_7,
            )) or 0)
            if recent_7 == 0:
                silent_people.append(person.name)
            if total == 0:
                sentiment_data.append({"person": person.name, "total_facts": 0,
                                       "sentiments": {}, "silent": True})
                continue
            dist: dict[str, int] = defaultdict(int)
            for f in facts:
                dist[f.sentiment or "neutral"] += 1
            neg_pct = (dist.get("negative", 0) / total) * 100
            negative_pcts.append(neg_pct)
            sentiment_data.append({"person": person.name, "total_facts": total,
                                   "sentiments": dict(dist), "negative_pct": round(neg_pct, 1),
                                   "silent": recent_7 == 0})

        blockers = [{"subject": b.subject, "value": b.value, "speaker": b.speaker}
                    for b in (await session.scalars(select(Fact).where(
                        Fact.workspace_id == workspace_id, Fact.fact_kind == FactKind.BLOCKER,
                        Fact.temporal_status == cur, Fact.valid_from >= since_14,
                    ).order_by(desc(Fact.valid_from)).limit(20))).all()]

        complaints = [{"subject": c.subject, "value": c.value, "speaker": c.speaker}
                      for c in (await session.scalars(select(Fact).where(
                          Fact.workspace_id == workspace_id, Fact.sentiment == "negative",
                          Fact.temporal_status == cur, Fact.valid_from >= since_14,
                      ).order_by(desc(Fact.valid_from)).limit(20))).all()]

        avg_negative = sum(negative_pcts) / len(negative_pcts) if negative_pcts else 0.0
        fb_morale, fb_score = _fallback_morale(avg_negative)

        prompt = MORALE_SENSING_PROMPT.format(
            sentiment_data=sentiment_data, blockers=blockers,
            complaints=complaints, silence=silent_people)
        result: dict[str, Any] = {}
        try:
            payload = parse_json_response(await get_llm().complete(prompt, max_tokens=600))
            if isinstance(payload, dict):
                result = payload
        except (LLMError, ValueError) as exc:
            log.warning("Morale sensing LLM failed for workspace %s: %s", workspace_id, exc)

        return {
            "team_morale": result.get("team_morale", fb_morale),
            "morale_score": result.get("morale_score", fb_score),
            "concerns": result.get("concerns", []),
            "positive_signals": result.get("positive_signals", []),
            "recommended_actions": result.get("recommended_actions", []),
            "should_warn_founder": result.get(
                "should_warn_founder", fb_morale in ("concerning", "declining")),
            "people_analyzed": len(people),
            "elapsed_ms": int((time.monotonic() - start) * 1000)}
    except Exception:
        log.exception("sense_team_morale failed for workspace %s", workspace_id)
        return {"team_morale": "stable", "morale_score": 0.5, "concerns": [],
                "positive_signals": [], "recommended_actions": [],
                "should_warn_founder": False, "people_analyzed": 0,
                "elapsed_ms": int((time.monotonic() - start) * 1000)}
