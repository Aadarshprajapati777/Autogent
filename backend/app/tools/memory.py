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

    # Supersede any current fact with the same id.
    existing = await ctx.db.scalars(
        select(Fact).where(
            Fact.workspace_id == ctx.workspace_id,
            Fact.fact_id == fid,
            Fact.temporal_status == TemporalStatus.CURRENT,
        )
    )
    for old in existing:
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
    )
    ctx.db.add(fact)
    await ctx.db.flush()
    return {"fact_id": fid, "stored": True}


@tool(
    name="memory_search_facts",
    description=(
        "Search long-term memory for facts matching a query. Searches subject, "
        "predicate, value, and topics (case-insensitive). Returns the most "
        "recent current facts. Use this to recall what you know before answering."
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
    q = f"%{args['query'].lower()}%"
    stmt = (
        select(Fact)
        .where(
            Fact.workspace_id == ctx.workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            or_(
                func.lower(Fact.subject).like(q),
                func.lower(Fact.predicate).like(q),
                func.lower(Fact.value).like(q),
            ),
        )
        .order_by(desc(Fact.created_at))
        .limit(args.get("limit", 20))
    )
    if args.get("project"):
        stmt = stmt.where(Fact.project == args["project"])
    if args.get("subject"):
        stmt = stmt.where(func.lower(Fact.subject) == args["subject"].lower())
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
                "topics": f.topics,
                "project": f.project,
                "speaker": f.speaker,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in facts
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
