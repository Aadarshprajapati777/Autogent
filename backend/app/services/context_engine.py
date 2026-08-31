"""Multi-signal context retrieval for PM decisions. Ports CloseLoopAI's contextengine."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.llm import LLMError, get_llm
from ..agent.parsing import parse_json_response
from ..agent.prompts import ASSOCIATIVE_RANKING_PROMPT, QUERY_INTENT_PROMPT
from ..models.memory import Fact, StateSnapshot, TemporalStatus
from .embeddings import embed_text

log = logging.getLogger(__name__)
_MAX_FACTS, _DENSE_TOP_K, _TRAVERSAL_LIMIT, _RECENT_LIMIT = 20, 50, 40, 30
_LLM_WEIGHT, _DENSE_WEIGHT = 0.7, 0.3
_RECENCY_HALF_LIFE_DAYS, _MIN_RELEVANCE = 90.0, 0.25

async def search_context(
    session: AsyncSession, workspace_id: Any, query: str,
    max_facts: int = 20, rerank: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    budget = max_facts or _MAX_FACTS
    intent, query_embedding, project_states, person_states = await asyncio.gather(
        _extract_intent(query), _embed_query(query),
        _latest_states(session, workspace_id, "project"),
        _latest_states(session, workspace_id, "person"),
    )
    topics = [str(t).strip().lower() for t in intent.get("topics") or []][:12]
    entities = [str(e) for e in intent.get("entities") or []][:12]
    hints = [str(k).strip().lower() for k in intent.get("fact_kind_hints") or []][:12]
    temporal_scope = str(intent.get("temporal_scope") or "any").strip().lower()
    vector_hits, traversal_hits, recent = await asyncio.gather(
        _vector_search(session, workspace_id, query_embedding, _DENSE_TOP_K),
        _traversal_search(session, workspace_id, topics, entities, _TRAVERSAL_LIMIT),
        _recent_facts(session, workspace_id, _RECENT_LIMIT),
    )
    candidates: dict[str, dict[str, Any]] = {}
    for fact in vector_hits + traversal_hits + recent:
        existing = candidates.setdefault(fact["fact_id"], fact)
        if "similarity" in fact:
            existing["similarity"] = fact["similarity"]
    now = datetime.now(timezone.utc)
    for fact in candidates.values():
        fact["is_overdue"] = _compute_is_overdue(fact, now)
    if temporal_scope == "current":
        candidates = {fid: f for fid, f in candidates.items()
                      if str(f.get("temporal_status") or "current") == TemporalStatus.CURRENT.value}
    scored = _dense_rank(list(candidates.values()), topics, hints)
    shortlist = scored[: max(budget * 3, 30)]
    associations: dict[str, dict[str, Any]] = {}
    if rerank:
        try:
            associations = await _rank_associatively(query, shortlist)
        except (LLMError, ValueError) as exc:
            log.warning("Associative ranking failed, dense-only fallback: %s", exc)
    selected = _select(shortlist, associations, budget, rerank and bool(associations))
    return {
        "query": query, "intent": intent, "facts": selected,
        "associations": {f["fact_id"]: associations.get(f["fact_id"], {}) for f in selected},
        "project_states": project_states, "person_states": person_states,
        "prompt_context": _render(selected, associations, project_states, person_states),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }

async def _extract_intent(query: str) -> dict[str, Any]:
    try:
        resp = await get_llm().complete(QUERY_INTENT_PROMPT.format(query=query), max_tokens=600)
        payload = parse_json_response(resp)
        return payload if isinstance(payload, dict) else {}
    except (LLMError, ValueError) as exc:
        log.warning("Intent extraction failed: %s", exc)
        return {}

async def _rank_associatively(query: str, facts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not facts:
        return {}
    lines = [f"- fact_id={f['fact_id']} [{f['fact_kind']}] {f['subject']} {f['predicate']} {f['value']}" for f in facts]
    resp = await get_llm().complete(
        ASSOCIATIVE_RANKING_PROMPT.format(query=query, facts="\n".join(lines)), max_tokens=1200)
    payload = parse_json_response(resp)
    scores: dict[str, dict[str, Any]] = {}
    for item in payload.get("scores", []) if isinstance(payload, dict) else []:
        fid = str(item.get("fact_id") or "")
        if fid:
            scores[fid] = {
                "relevance": max(0.0, min(1.0, float(item.get("relevance") or 0.0))),
                "connection": str(item.get("connection") or "contextual"),
                "reasoning": str(item.get("reasoning") or "")[:280],
            }
    return scores

async def _embed_query(query: str) -> list[float]:
    try:
        return await asyncio.to_thread(embed_text, query)
    except Exception as exc:
        log.warning("Query embedding failed: %s", exc)
        return []

def _fact_to_dict(fact: Fact, similarity: float | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {
        "fact_id": fact.fact_id, "subject": fact.subject, "predicate": fact.predicate,
        "value": fact.value, "fact_kind": fact.fact_kind.value if fact.fact_kind else "fact",
        "topics": fact.topics or [], "entities": fact.entities or [], "project": fact.project,
        "task": fact.task, "sentiment": fact.sentiment,
        "temporal_status": fact.temporal_status.value if fact.temporal_status else "current",
        "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
        "due_date": fact.due_date, "speaker": fact.speaker,
        "speaker_role": fact.speaker_role.value if fact.speaker_role else "",
        "confidence": float(fact.confidence or 0.5),
    }
    if similarity is not None:
        d["similarity"] = similarity
    return d

async def _vector_search(session: AsyncSession, workspace_id: Any,
                         embedding: list[float], limit: int) -> list[dict[str, Any]]:
    if not embedding:
        return []
    distance = Fact.embedding.cosine_distance(embedding)
    rows = (await session.execute(
        select(Fact, distance.label("distance")).where(
            Fact.workspace_id == workspace_id, Fact.embedding.isnot(None))
        .order_by("distance").limit(limit))).all()
    return [_fact_to_dict(f, max(0.0, 1.0 - dist)) for f, dist in rows]

async def _traversal_search(session: AsyncSession, workspace_id: Any,
                            topics: list[str], entities: list[str], limit: int) -> list[dict[str, Any]]:
    if not topics and not entities:
        return []
    stmt = select(Fact).where(Fact.workspace_id == workspace_id, Fact.temporal_status == TemporalStatus.CURRENT)
    if topics:
        stmt = stmt.where(Fact.topics.op("?|")(topics))
    if entities:
        stmt = stmt.where(Fact.entities.op("?|")(entities))
    rows = (await session.scalars(stmt.limit(limit))).all()
    return [_fact_to_dict(f) for f in rows]

async def _recent_facts(session: AsyncSession, workspace_id: Any, limit: int) -> list[dict[str, Any]]:
    rows = (await session.scalars(
        select(Fact).where(Fact.workspace_id == workspace_id, Fact.temporal_status == TemporalStatus.CURRENT)
        .order_by(desc(Fact.valid_from)).limit(limit))).all()
    return [_fact_to_dict(f) for f in rows]

async def _latest_states(session: AsyncSession, workspace_id: Any, entity_type: str) -> list[dict[str, Any]]:
    rows = (await session.scalars(
        select(StateSnapshot).where(StateSnapshot.workspace_id == workspace_id, StateSnapshot.entity_type == entity_type)
        .order_by(desc(StateSnapshot.created_at)))).all()
    latest: dict[str, StateSnapshot] = {}
    for snap in rows:
        latest.setdefault(snap.entity_name, snap)
    return [{"name": s.entity_name, "state": s.state, "score": float(s.score or 0.0),
             "risk_signals": s.risk_signals or [], "summary": s.summary or "",
             "open_commitments": s.open_commitments, "missed_or_late": s.missed_or_late,
             "days_since_last_seen": s.days_since_last_seen} for s in latest.values()]

def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        m = datetime.fromisoformat(s)
        return m.replace(tzinfo=timezone.utc) if m.tzinfo is None else m
    except (ValueError, TypeError):
        return None

def _compute_is_overdue(fact: dict[str, Any], now: datetime) -> bool:
    if fact.get("fact_kind") != "commitment" or not fact.get("due_date"):
        return False
    if str(fact.get("temporal_status") or "current") != TemporalStatus.CURRENT.value:
        return False
    due = _parse_date(fact["due_date"])
    return bool(due and due < now)

def recency_score(valid_from: str | None) -> float:
    moment = _parse_date(valid_from)
    if not moment:
        return 0.5
    age_days = max(0.0, (datetime.now(timezone.utc) - moment).total_seconds() / 86400.0)
    return 0.5 ** (age_days / _RECENCY_HALF_LIFE_DAYS)

def _dense_rank(facts: list[dict[str, Any]], topics: list[str],
                fact_kind_hints: list[str] | None = None) -> list[dict[str, Any]]:
    topic_set, hint_set = set(topics), set(fact_kind_hints or [])
    for fact in facts:
        sim = float(fact.get("similarity") or 0.0)
        overlap = len(topic_set & set(fact.get("topics") or [])) / len(topic_set) if topic_set else 0.0
        kind = 0.15 if hint_set and fact.get("fact_kind", "").lower() in hint_set else 0.0
        overdue = 0.1 if fact.get("is_overdue") else 0.0
        role = (fact.get("speaker_role") or "").lower()
        src = 0.08 if role == "founder" else 0.03 if role == "engineer" else 0.0
        fact["dense_score"] = (0.5 * sim + 0.08 * overlap + 0.10 * recency_score(fact.get("valid_from"))
                                + kind + overdue + src + 0.12 * float(fact.get("confidence") or 0.5))
    return sorted(facts, key=lambda f: f["dense_score"], reverse=True)

def _select(facts: list[dict[str, Any]], associations: dict[str, dict[str, Any]],
            budget: int, rerank: bool) -> list[dict[str, Any]]:
    for fact in facts:
        llm = associations.get(fact["fact_id"], {}).get("relevance", 0.0)
        fact["final_score"] = _LLM_WEIGHT * llm + _DENSE_WEIGHT * fact["dense_score"] if rerank and associations else fact["dense_score"]
    ranked = sorted(facts, key=lambda f: f["final_score"], reverse=True)
    selected = [f for f in ranked if f["final_score"] >= _MIN_RELEVANCE]
    return (selected or ranked[:5])[:budget]

def _days_between(date_str: str | None, now: datetime) -> int | None:
    moment = _parse_date(date_str)
    return max(0, (now - moment).days) if moment else None

def _render(facts: list[dict[str, Any]], associations: dict[str, dict[str, Any]],
            project_states: list[dict[str, Any]] | None = None,
            person_states: list[dict[str, Any]] | None = None) -> str:
    now = datetime.now(timezone.utc)
    sections: list[str] = []
    if facts:
        lines = ["RELEVANT COMPANY MEMORY:"]
        for fact in facts:
            topics = ",".join(fact.get("topics") or [])
            od = _days_between(fact.get("due_date"), now) if fact.get("is_overdue") else None
            ov = f" [OVERDUE by {od} days]" if od is not None else (" [OVERDUE]" if fact.get("is_overdue") else "")
            ct = " [LOW CONFIDENCE]" if fact.get("confidence") is not None and float(fact["confidence"]) < 0.4 else ""
            line = f"- [{fact['fact_kind']}|{topics}]{ov}{ct} {fact['subject']} {fact['predicate']} {fact['value']}"
            if fact.get("speaker"):
                line += f" (from {fact['speaker']}" + (f", {fact['valid_from'][:10]})" if fact.get("valid_from") else ")")
            if fact.get("due_date"):
                line += f" [due: {fact['due_date'][:10]}]"
            if associations.get(fact["fact_id"], {}).get("reasoning"):
                line += f"\n  -> {associations[fact['fact_id']]['reasoning']}"
            lines.append(line)
        sections.append("\n".join(lines))
    else:
        sections.append("No relevant memory found.")
    if project_states:
        sections.append(_render_states("CURRENT PROJECT STATES:", project_states))
    if person_states:
        sections.append(_render_states("CURRENT PERSON CREDIBILITY:", person_states))
    return "\n\n".join(sections)

def _render_states(header: str, states: list[dict[str, Any]]) -> str:
    lines = [header]
    for st in states:
        signals = "; ".join(st.get("risk_signals") or []) or "none"
        sil = f", last seen {st['days_since_last_seen']}d ago" if st.get("days_since_last_seen") is not None else ""
        lines.append(f"- {st['name']} [{st['state']}, score {st['score']}{sil}]: {st.get('summary') or 'no summary'} (risks: {signals})")
    return "\n".join(lines)
