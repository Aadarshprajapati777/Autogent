"""Fact extraction service — the agent's memory ingestion layer.

Takes a conversation message (Slack, meeting, chat), runs the fact extraction
prompt via the LLM, and stores each extracted fact as a Fact row with
embedding, episode provenance, and relation links. Also upserts Person and
Project rows when mentioned.

This replaces kgmemory's /memory/ingest endpoint — everything stays in the
same Postgres DB, no separate service needed.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.llm import LLMError, get_llm
from ..agent.parsing import parse_json_response
from ..agent.prompts import FACT_EXTRACTION_PROMPT
from ..models.memory import (
    Fact,
    FactKind,
    FactRelation,
    IngestEpisode,
    Person,
    PersonRole,
    Project,
    ProjectStatus,
    SpeakerRole,
    TemporalStatus,
)
from ..services.embeddings import embed_text

log = logging.getLogger(__name__)

FACT_NAMESPACE = uuid.UUID("7c9e6f5a-2b4d-4f1e-9a3c-8d7b6e5f4a3b")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
MAX_MESSAGE_CHARS = 200_000
CHUNK_CHARS = 4000

# Words that indicate completion vs in-progress/blocked states.
_COMPLETION_WORDS = {"completed", "done", "shipped", "finished", "delivered",
                     "merged", "deployed", "resolved", "fixed"}
_PROGRESS_WORDS = {"working on", "in progress", "blocked", "stuck", "started",
                   "attempting", "trying", "wip", "pending"}


class ExtractionError(Exception):
    pass


def _fact_id(subject: str, predicate: str, value: str, topics: list[str]) -> str:
    sig = "|".join(
        [subject.strip().lower(), predicate.strip().lower(), value.strip().lower(),
         ",".join(sorted(topics))]
    )
    return str(uuid.uuid5(FACT_NAMESPACE, sig))


def _chunk_message(message: str, limit: int = CHUNK_CHARS) -> list[str]:
    if len(message) <= limit:
        return [message]
    chunks: list[str] = []
    current = ""
    for paragraph in message.split("\n\n"):
        pieces = [paragraph] if len(paragraph) <= limit else _split_sentences(paragraph, limit)
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > limit:
                chunks.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def _split_sentences(text: str, limit: int) -> list[str]:
    pieces, current = [], ""
    for sentence in _SENTENCE_RE.split(text):
        while len(sentence) > limit:
            pieces.append(sentence[:limit])
            sentence = sentence[limit:]
        if current and len(current) + len(sentence) + 1 > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        pieces.append(current)
    return pieces


def _build_fact_from_raw(
    raw: dict[str, Any],
    *,
    speaker: str,
    speaker_role: str,
    episode_id: str,
    timestamp: datetime,
    project: str | None,
    workspace_id: uuid.UUID,
) -> dict[str, Any] | None:
    """Convert a raw extracted fact dict into the fields needed for a Fact row."""
    subject = str(raw.get("subject") or "").strip()
    predicate = str(raw.get("predicate") or "").strip()
    value = str(raw.get("value") or "").strip()
    if not (subject and predicate and value):
        return None
    try:
        kind = FactKind(str(raw.get("fact_kind") or "fact"))
    except ValueError:
        kind = FactKind.FACT
    try:
        speaker_role_enum = SpeakerRole(speaker_role)
    except ValueError:
        speaker_role_enum = SpeakerRole.OTHER
    topics = [str(t).strip().lower() for t in raw.get("topics") or [] if t.strip()][:8]
    fid = _fact_id(subject, predicate, value, topics)
    return {
        "fact_id": fid,
        "workspace_id": workspace_id,
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "fact_kind": kind,
        "topics": topics,
        "entities": [str(e) for e in raw.get("entities") or []][:16],
        "project": raw.get("project") or project,
        "task": raw.get("task"),
        "numeric_value": raw.get("numeric_value"),
        "unit": raw.get("unit"),
        "sentiment": str(raw.get("sentiment") or "neutral"),
        "temporal_hint": str(raw.get("temporal_hint") or "current"),
        "due_date": raw.get("due_date"),
        "evidence_quote": raw.get("evidence_quote"),
        "speaker": speaker,
        "speaker_role": speaker_role_enum,
        "episode_id": episode_id,
        "temporal_status": TemporalStatus.CURRENT,
        "valid_from": timestamp,
    }


async def ingest_message(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    speaker: str,
    speaker_role: str = "other",
    message: str,
    channel: str = "api",
    project: str | None = None,
) -> dict[str, Any]:
    """Ingest a conversation message: record the episode, extract facts via LLM,
    store them with embeddings, upsert people/projects, and link relations.

    This is the main entry point — called by the Slack reply handler, the
    onboarding flow, meeting sync, and the agent's memory_ingest_message tool.
    """
    message = message.strip()[:MAX_MESSAGE_CHARS]
    if not message:
        return {"episode_id": None, "facts_extracted": 0, "error": "empty message"}

    now = datetime.now(timezone.utc)
    episode_id = str(uuid.uuid4())

    # Record the episode for provenance
    try:
        speaker_role_enum = SpeakerRole(speaker_role)
    except ValueError:
        speaker_role_enum = SpeakerRole.OTHER

    ep = IngestEpisode(
        workspace_id=workspace_id,
        episode_id=episode_id,
        speaker=speaker,
        speaker_role=speaker_role_enum,
        channel=channel,
        message=message,
        project=project,
        occurred_at=now,
    )
    session.add(ep)
    await session.flush()

    # Extract facts from all chunks
    chunks = _chunk_message(message)
    all_facts: list[dict[str, Any]] = []
    all_relations: list[dict[str, str]] = []
    failed_chunks = 0

    for chunk in chunks:
        try:
            facts, relations = await _extract_chunk(
                chunk, speaker=speaker, speaker_role=speaker_role,
                episode_id=episode_id, timestamp=now, project=project,
                workspace_id=workspace_id,
            )
            all_facts.extend(facts)
            all_relations.extend(relations)
        except Exception as exc:
            failed_chunks += 1
            log.warning("Extraction failed for a chunk: %s", exc)

    if failed_chunks == len(chunks) and chunks:
        log.error("All extraction chunks failed for episode %s", episode_id)
        return {"episode_id": episode_id, "facts_extracted": 0, "error": "extraction failed"}

    # Dedupe by fact_id
    seen: dict[str, dict] = {}
    for f in all_facts:
        seen.setdefault(f["fact_id"], f)
    unique_facts = list(seen.values())

    # Store facts with embeddings
    created = 0
    invalidated = 0
    for fdata in unique_facts:
        fid = fdata["fact_id"]
        # Check if a current fact with this id already exists
        existing = await session.scalar(
            select(Fact).where(
                Fact.workspace_id == workspace_id,
                Fact.fact_id == fid,
                Fact.temporal_status == TemporalStatus.CURRENT,
            )
        )
        if existing:
            continue  # Already current, no change needed

        # Mark old versions as superseded
        old_rows = (await session.scalars(
            select(Fact).where(
                Fact.workspace_id == workspace_id,
                Fact.fact_id == fid,
            )
        )).all()
        for old in old_rows:
            if old.temporal_status == TemporalStatus.CURRENT:
                old.temporal_status = TemporalStatus.SUPERSEDED
                old.valid_until = now
                old.superseded_by = fid
                invalidated += 1

        # Supersede conflicting single-value facts (identity, availability)
        if fdata["fact_kind"] in (FactKind.IDENTITY, FactKind.AVAILABILITY):
            conflicts = (await session.scalars(
                select(Fact).where(
                    Fact.workspace_id == workspace_id,
                    Fact.temporal_status == TemporalStatus.CURRENT,
                    Fact.fact_id != fid,
                    func.lower(Fact.subject) == fdata["subject"].lower(),
                    func.lower(Fact.predicate) == fdata["predicate"].lower(),
                )
            )).all()
            for c in conflicts:
                c.temporal_status = TemporalStatus.SUPERSEDED
                c.valid_until = now
                c.superseded_by = fid
                invalidated += 1

        # Generate embedding
        embed_input = f"{fdata['subject']} {fdata['predicate']} {fdata['value']} {' '.join(fdata['topics'])}"
        try:
            embedding = embed_text(embed_input)
        except Exception as exc:
            log.warning("Embedding failed for fact %s: %s", fid, exc)
            embedding = None

        fact = Fact(
            fact_id=fid,
            workspace_id=workspace_id,
            subject=fdata["subject"],
            predicate=fdata["predicate"],
            value=fdata["value"],
            fact_kind=fdata["fact_kind"],
            topics=fdata["topics"],
            entities=fdata["entities"],
            project=fdata["project"],
            task=fdata["task"],
            numeric_value=fdata.get("numeric_value"),
            unit=fdata.get("unit"),
            sentiment=fdata["sentiment"],
            temporal_hint=fdata["temporal_hint"],
            due_date=fdata["due_date"],
            evidence_quote=fdata["evidence_quote"],
            speaker=fdata["speaker"],
            speaker_role=fdata["speaker_role"],
            episode_id=fdata["episode_id"],
            temporal_status=TemporalStatus.CURRENT,
            valid_from=fdata["valid_from"],
            embedding=embedding,
        )
        session.add(fact)
        created += 1

    # Link relations
    relations_created = 0
    for rel in all_relations:
        source = rel.get("from", "")
        target = rel.get("to", "")
        rtype = rel.get("type", "").strip().lower()
        if source and target and rtype in {"causes", "influences", "blocks", "depends_on"}:
            existing_rel = await session.scalar(
                select(FactRelation).where(
                    FactRelation.workspace_id == workspace_id,
                    FactRelation.from_fact_id == source,
                    FactRelation.to_fact_id == target,
                    FactRelation.relation_type == rtype,
                )
            )
            if not existing_rel:
                session.add(FactRelation(
                    workspace_id=workspace_id,
                    from_fact_id=source,
                    to_fact_id=target,
                    relation_type=rtype,
                ))
                relations_created += 1

    # Upsert person if the speaker is a real name
    if speaker and speaker.strip().lower() not in ("system", "meeting", "unknown"):
        await _upsert_person(session, workspace_id, speaker, speaker_role)

    # Upsert project if mentioned
    if project:
        await _upsert_project(session, workspace_id, project)

    await session.flush()

    result = {
        "episode_id": episode_id,
        "facts_extracted": len(unique_facts),
        "facts_created": created,
        "facts_invalidated": invalidated,
        "relations_created": relations_created,
        "failed_chunks": failed_chunks,
    }
    log.info("Ingested message from %s: %s", speaker, result)
    return result


async def _extract_chunk(
    chunk: str,
    *,
    speaker: str,
    speaker_role: str,
    episode_id: str,
    timestamp: datetime,
    project: str | None,
    workspace_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Extract facts from a single chunk via the LLM."""
    prompt = FACT_EXTRACTION_PROMPT.format(
        speaker=speaker,
        speaker_role=speaker_role,
        timestamp=timestamp.isoformat(),
        message=chunk,
    )
    response = await get_llm().complete(prompt, max_tokens=4000)
    payload = parse_json_response(response)
    if not isinstance(payload, dict):
        raise ValueError("Extraction payload is not an object")

    raw_facts = payload.get("facts") or []
    raw_relations = payload.get("relations") or []

    facts: list[dict[str, Any]] = []
    local_to_fact: dict[str, str] = {}
    for raw in raw_facts:
        if not isinstance(raw, dict):
            continue
        fdata = _build_fact_from_raw(
            raw, speaker=speaker, speaker_role=speaker_role,
            episode_id=episode_id, timestamp=timestamp, project=project,
            workspace_id=workspace_id,
        )
        if fdata is None:
            continue
        local_id = str(raw.get("local_id") or "")
        if local_id:
            local_to_fact[local_id] = fdata["fact_id"]
        facts.append(fdata)

    # Resolve relations from local_ids to fact_ids
    relations: list[dict[str, str]] = []
    for raw in raw_relations:
        if not isinstance(raw, dict):
            continue
        source = local_to_fact.get(str(raw.get("from") or ""))
        target = local_to_fact.get(str(raw.get("to") or ""))
        rtype = str(raw.get("type") or "").strip().lower()
        if source and target and rtype in {"causes", "influences", "blocks", "depends_on"}:
            relations.append({"from": source, "to": target, "type": rtype})

    return facts, relations


async def _upsert_person(
    session: AsyncSession, workspace_id: uuid.UUID, name: str, role: str = "other"
) -> Person:
    """Create or update a Person row for someone mentioned in a conversation."""
    person = await session.scalar(
        select(Person).where(
            Person.workspace_id == workspace_id,
            func.lower(Person.name) == name.lower(),
        )
    )
    if person is None:
        try:
            person_role = PersonRole(role)
        except ValueError:
            person_role = PersonRole.OTHER
        person = Person(
            workspace_id=workspace_id,
            name=name,
            role=person_role,
        )
        session.add(person)
        await session.flush()
    return person


async def _upsert_project(
    session: AsyncSession, workspace_id: uuid.UUID, name: str
) -> Project:
    """Create or update a Project row."""
    project = await session.scalar(
        select(Project).where(
            Project.workspace_id == workspace_id,
            func.lower(Project.name) == name.lower(),
        )
    )
    if project is None:
        project = Project(
            workspace_id=workspace_id,
            name=name,
            status=ProjectStatus.PLANNING,
        )
        session.add(project)
        await session.flush()
    return project


async def link_commitment_fulfillment(
    session: AsyncSession, workspace_id: uuid.UUID, fact: Fact
) -> int:
    """When a status_update indicates completion, find matching open
    commitments from the same person about the same subject and link them.
    Returns the number of commitments fulfilled."""
    if fact.fact_kind != FactKind.STATUS_UPDATE:
        return 0
    value_lower = fact.value.strip().lower()
    if not any(w in value_lower for w in _COMPLETION_WORDS):
        return 0

    commitments = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            Fact.fact_kind == FactKind.COMMITMENT,
            func.lower(Fact.subject) == fact.subject.strip().lower(),
        )
    )).all()

    linked = 0
    for c in commitments:
        if c.speaker and fact.speaker and c.speaker.lower() != fact.speaker.lower():
            continue
        if _is_completion_match(c.value, fact.value):
            # Mark the commitment as superseded by the completion
            c.temporal_status = TemporalStatus.SUPERSEDED
            c.valid_until = datetime.now(timezone.utc)
            c.superseded_by = fact.fact_id
            linked += 1
    return linked


def _is_completion_match(commitment_value: str, completion_value: str) -> bool:
    """Check if a completion value plausibly refers to the same thing as
    a commitment value. Uses word overlap to handle phrasing differences."""
    def words(text: str) -> set[str]:
        return {w for w in text.lower().split() if len(w) > 2}
    commitment_words = words(commitment_value)
    completion_words = words(completion_value)
    if not commitment_words:
        return True
    overlap = commitment_words & completion_words
    return len(overlap) / len(commitment_words) >= 0.4
