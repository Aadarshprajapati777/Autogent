"""Memory tools — the agent reading and writing its own brain.

These replace the kgmemory microservice's /memory/* and /context/* endpoints.
Because memory now lives in the same DB, the tools are plain SQLAlchemy
queries instead of HTTP calls. The agent uses them to recall facts, log new
facts from conversations, search its memory, and invalidate stale facts.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import desc, func, or_, select

from ..agent.registry import tool
from ..models.memory import (
    Fact,
    FactKind,
    IngestEpisode,
    Person,
    Project,
    SpeakerRole,
    TemporalStatus,
)
from ..services.embeddings import embed_text

FACT_NAMESPACE = uuid.UUID("7c9e6f5a-2b4d-4f1e-9a3c-8d7b6e5f4a3b")


def _fact_id(subject: str, predicate: str, value: str, topics: list[str]) -> str:
    sig = "|".join(
        [subject.strip().lower(), predicate.strip().lower(), value.strip().lower(),
         ",".join(sorted(topics))]
    )
    return str(uuid.uuid5(FACT_NAMESPACE, sig))


@tool(
    name="memory_add_fact",
    description=(
        "Store a fact in long-term memory. Use this when the user tells you "
        "something worth remembering: a commitment, a decision, a skill, a "
        "preference, a blocker, etc. Re-storing the same (subject, predicate, "
        "value) supersedes the old fact instead of duplicating."
    ),
    parameters={
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Who/what the fact is about"},
            "predicate": {"type": "string", "description": "The relationship/attribute"},
            "value": {"type": "string", "description": "The value of the attribute"},
            "fact_kind": {
                "type": "string",
                "enum": [k.value for k in FactKind],
                "default": "fact",
            },
            "topics": {"type": "array", "items": {"type": "string"}, "default": []},
            "project": {"type": "string"},
            "speaker": {"type": "string"},
            "evidence_quote": {"type": "string"},
        },
        "required": ["subject", "predicate", "value"],
    },
)
async def memory_add_fact(ctx, args: dict) -> dict:
    topics = [t.strip().lower() for t in args.get("topics", []) if t.strip()][:8]
    fid = _fact_id(args["subject"], args["predicate"], args["value"], topics)
    now = datetime.now(timezone.utc)

    # If a CURRENT fact with the same id exists, keep it as-is (same content).
    # If a non-current (superseded/invalidated) fact exists, create a new
    # CURRENT version and mark the old one as superseded.
    existing = await ctx.db.scalar(
        select(Fact).where(
            Fact.workspace_id == ctx.workspace_id,
            Fact.fact_id == fid,
            Fact.temporal_status == TemporalStatus.CURRENT,
        )
    )
    if existing:
        # Same fact, still current — no change needed.
        return {"fact_id": fid, "stored": True, "already_current": True}

    # Mark any old versions as superseded.
    old_rows = (await ctx.db.scalars(
        select(Fact).where(
            Fact.workspace_id == ctx.workspace_id,
            Fact.fact_id == fid,
        )
    )).all()
    for old in old_rows:
        if old.temporal_status == TemporalStatus.CURRENT:
            old.temporal_status = TemporalStatus.SUPERSEDED
            old.valid_until = now
            old.superseded_by = fid

    fact = Fact(
        workspace_id=ctx.workspace_id,
        fact_id=fid,
        subject=args["subject"],
        predicate=args["predicate"],
        value=args["value"],
        fact_kind=FactKind(args.get("fact_kind", "fact")),
        topics=topics,
        project=args.get("project"),
        speaker=args.get("speaker"),
        evidence_quote=args.get("evidence_quote"),
        temporal_status=TemporalStatus.CURRENT,
        valid_from=now,
        embedding=embed_text(f"{args['subject']} {args['predicate']} {args['value']} {' '.join(topics)}"),
    )
    ctx.db.add(fact)
    await ctx.db.flush()
    return {"fact_id": fid, "stored": True, "superseded": len(old_rows)}


@tool(
    name="memory_search_facts",
    description=(
        "Search long-term memory for facts matching a query. Uses hybrid "
        "retrieval: semantic vector search + keyword matching + recency "
        "boost, then reranks by combined score. Returns the most relevant "
        "current facts. Use this to recall what you know before answering."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for"},
            "project": {"type": "string", "description": "Filter to a project"},
            "subject": {"type": "string", "description": "Filter to a subject (person/thing)"},
            "fact_kind": {"type": "string", "enum": [k.value for k in FactKind]},
            "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
        },
        "required": ["query"],
    },
)
async def memory_search_facts(ctx, args: dict) -> dict:
    """Hybrid retrieval: combine vector similarity, keyword match, and recency.

    1. Vector search: embed the query, find nearest facts by cosine distance
       via pgvector (if embeddings exist).
    2. Keyword search: ILIKE on subject/predicate/value (fallback + complement).
    3. Merge results, apply recency boost, rerank by combined score.
    """
    from pgvector.sqlalchemy import Vector

    query_text = args["query"]
    limit = args.get("limit", 20)
    base_filters = [
        Fact.workspace_id == ctx.workspace_id,
        Fact.temporal_status == TemporalStatus.CURRENT,
    ]
    if args.get("project"):
        base_filters.append(Fact.project == args["project"])
    if args.get("subject"):
        base_filters.append(func.lower(Fact.subject) == args["subject"].lower())
    if args.get("fact_kind"):
        base_filters.append(Fact.fact_kind == FactKind(args["fact_kind"]))

    # --- 1. Vector search via pgvector ---
    vector_results: dict[str, float] = {}
    try:
        query_embedding = embed_text(query_text)
        if query_embedding:
            vec_stmt = (
                select(
                    Fact,
                    Fact.embedding.cosine_distance(query_embedding).label("distance"),
                )
                .where(*base_filters, Fact.embedding.isnot(None))
                .order_by("distance")
                .limit(limit * 3)
            )
            rows = (await ctx.db.execute(vec_stmt)).all()
            for fact, distance in rows:
                # Convert distance (0=identical, 2=opposite) to similarity (0-1)
                similarity = max(0.0, 1.0 - (distance / 2.0))
                vector_results[str(fact.id)] = similarity
    except Exception as exc:
        # If vector search fails (no embeddings yet, model not loaded), fall
        # back to keyword-only search.
        import logging
        logging.getLogger(__name__).warning("Vector search failed: %s", exc)

    # --- 2. Keyword search (ILIKE) ---
    q = f"%{query_text.lower()}%"
    kw_stmt = (
        select(Fact)
        .where(
            *base_filters,
            or_(
                func.lower(Fact.subject).like(q),
                func.lower(Fact.predicate).like(q),
                func.lower(Fact.value).like(q),
            ),
        )
        .order_by(desc(Fact.created_at))
        .limit(limit * 3)
    )
    kw_facts = (await ctx.db.scalars(kw_stmt)).all()

    # --- 3. Merge + rerank ---
    # Collect all candidate facts by id
    all_ids = set(vector_results.keys()) | {str(f.id) for f in kw_facts}
    if not all_ids:
        return {"count": 0, "facts": []}

    # Fetch all candidates in one query
    from uuid import UUID as PyUUID
    candidate_stmt = select(Fact).where(
        Fact.id.in_([PyUUID(fid) for fid in all_ids])
    )
    candidates = {str(f.id): f for f in (await ctx.db.scalars(candidate_stmt)).all()}

    # Score each candidate: vector_score (0-1) + keyword_score (0 or 1) + recency_boost
    now = datetime.now(timezone.utc)
    scored: list[tuple[float, Fact]] = []
    for fid, fact in candidates.items():
        vec_score = vector_results.get(fid, 0.0)
        kw_score = 1.0 if (
            query_text.lower() in (fact.subject or "").lower()
            or query_text.lower() in (fact.predicate or "").lower()
            or query_text.lower() in (fact.value or "").lower()
        ) else 0.0
        # Recency boost: newer facts get a small bonus (max 0.15)
        if fact.created_at:
            age_days = (now - fact.created_at.replace(tzinfo=timezone.utc)).days
            recency = max(0.0, 0.15 * (1.0 - age_days / 30.0))
        else:
            recency = 0.0
        # Weighted combination: vector search is primary, keyword is a strong
        # signal, recency is a tiebreaker.
        combined = (vec_score * 0.6) + (kw_score * 0.25) + recency
        scored.append((combined, fact))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    return {
        "count": len(top),
        "facts": [
            {
                "fact_id": f.fact_id,
                "subject": f.subject,
                "predicate": f.predicate,
                "value": f.value,
                "fact_kind": f.fact_kind.value,
                "topics": f.topics,
                "project": f.project,
                "speaker": f.speaker,
                "score": round(score, 3),
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for score, f in top
        ],
    }


@tool(
    name="memory_list_facts",
    description="List facts in memory, optionally filtered by subject, project, or kind.",
    parameters={
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "project": {"type": "string"},
            "fact_kind": {"type": "string", "enum": [k.value for k in FactKind]},
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
        },
    },
)
async def memory_list_facts(ctx, args: dict) -> dict:
    stmt = (
        select(Fact)
        .where(
            Fact.workspace_id == ctx.workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
        )
        .order_by(desc(Fact.created_at))
        .limit(args.get("limit", 50))
    )
    if args.get("subject"):
        stmt = stmt.where(func.lower(Fact.subject) == args["subject"].lower())
    if args.get("project"):
        stmt = stmt.where(Fact.project == args["project"])
    if args.get("fact_kind"):
        stmt = stmt.where(Fact.fact_kind == FactKind(args["fact_kind"]))

    facts = (await ctx.db.scalars(stmt)).all()
    return {
        "count": len(facts),
        "facts": [
            {
                "fact_id": f.fact_id,
                "subject": f.subject,
                "predicate": f.predicate,
                "value": f.value,
                "fact_kind": f.fact_kind.value,
                "project": f.project,
            }
            for f in facts
        ],
    }


@tool(
    name="memory_invalidate_fact",
    description="Mark a fact as no longer true (invalidated). Use when you learn a fact changed.",
    parameters={
        "type": "object",
        "properties": {"fact_id": {"type": "string"}},
        "required": ["fact_id"],
    },
)
async def memory_invalidate_fact(ctx, args: dict) -> dict:
    fact = await ctx.db.scalar(
        select(Fact).where(
            Fact.workspace_id == ctx.workspace_id,
            Fact.fact_id == args["fact_id"],
        )
    )
    if not fact:
        return {"invalidated": False, "error": "fact not found"}
    fact.temporal_status = TemporalStatus.INVALIDATED
    fact.valid_until = datetime.now(timezone.utc)
    await ctx.db.flush()
    return {"invalidated": True, "fact_id": args["fact_id"]}


@tool(
    name="memory_ingest_message",
    description=(
        "Ingest a conversation message into memory. Records the episode and "
        "extracts simple facts (subject 'X said Y'). For richer extraction use "
        "the meeting extraction flow. Use this for Slack messages or chat lines "
        "the agent should remember."
    ),
    parameters={
        "type": "object",
        "properties": {
            "speaker": {"type": "string"},
            "message": {"type": "string"},
            "channel": {"type": "string", "default": "api"},
            "project": {"type": "string"},
        },
        "required": ["speaker", "message"],
    },
)
async def memory_ingest_message(ctx, args: dict) -> dict:
    now = datetime.now(timezone.utc)
    episode_id = str(uuid.uuid4())
    ep = IngestEpisode(
        workspace_id=ctx.workspace_id,
        episode_id=episode_id,
        speaker=args["speaker"],
        channel=args.get("channel", "api"),
        message=args["message"],
        project=args.get("project"),
        occurred_at=now,
    )
    ctx.db.add(ep)
    await ctx.db.flush()
    return {"episode_id": episode_id, "ingested": True}
