"""Meeting tools. The agent can list meetings, read transcripts, and trigger
extraction to get decisions and action items. After extraction, the agent
can assign tasks to people and create tickets in Jira/Linear.
"""
from __future__ import annotations

from sqlalchemy import select, desc

from ..agent.registry import tool
from ..models.meetings import (
    Meeting, MeetingExtraction, MeetingStatus, Speaker, Transcript, TranscriptChunk,
)
from ..models.work import Decision, TaskCandidate


@tool(
    name="meetings_list",
    description="List recent meetings for this workspace with their status.",
    parameters={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "default": 10},
        },
    },
)
async def meetings_list(ctx, args: dict) -> dict:
    meetings = (await ctx.db.scalars(
        select(Meeting)
        .where(Meeting.workspace_id == ctx.workspace_id)
        .order_by(desc(Meeting.created_at))
        .limit(args.get("limit", 10))
    )).all()
    return {
        "count": len(meetings),
        "meetings": [
            {
                "id": str(m.id),
                "title": m.title,
                "status": m.status.value,
                "started_at": m.started_at.isoformat() if m.started_at else None,
                "ended_at": m.ended_at.isoformat() if m.ended_at else None,
            }
            for m in meetings
        ],
    }


@tool(
    name="meeting_get_transcript",
    description="Get the full transcript of a meeting. Returns chunks with speaker names.",
    parameters={
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string", "description": "Meeting UUID"},
        },
        "required": ["meeting_id"],
    },
)
async def meeting_get_transcript(ctx, args: dict) -> dict:
    from uuid import UUID
    meeting = await ctx.db.scalar(
        select(Meeting).where(
            Meeting.workspace_id == ctx.workspace_id,
            Meeting.id == UUID(args["meeting_id"]),
        )
    )
    if not meeting:
        return {"error": "Meeting not found"}

    transcript = await ctx.db.scalar(
        select(Transcript).where(Transcript.meeting_id == meeting.id)
    )
    if not transcript:
        return {"error": "No transcript available for this meeting"}

    speakers = (await ctx.db.scalars(
        select(Speaker).where(Speaker.meeting_id == meeting.id)
    )).all()
    speaker_map = {str(s.id): s.display_name for s in speakers}

    chunks = (await ctx.db.scalars(
        select(TranscriptChunk)
        .where(TranscriptChunk.transcript_id == transcript.id, TranscriptChunk.is_final.is_(True))
        .order_by(TranscriptChunk.sequence)
    )).all()

    return {
        "meeting_title": meeting.title,
        "status": transcript.status,
        "speakers": [{"id": str(s.id), "name": s.display_name} for s in speakers],
        "chunks": [
            {
                "speaker": speaker_map.get(str(c.speaker_id), "Unknown") if c.speaker_id else "Unknown",
                "text": c.text,
            }
            for c in chunks
        ],
    }


@tool(
    name="meeting_get_extraction",
    description=(
        "Get the AI extraction results for a meeting — decisions, action items, "
        "and risks. Use this to see what was decided and what tasks were created."
    ),
    parameters={
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string", "description": "Meeting UUID"},
        },
        "required": ["meeting_id"],
    },
)
async def meeting_get_extraction(ctx, args: dict) -> dict:
    from uuid import UUID
    meeting = await ctx.db.scalar(
        select(Meeting).where(
            Meeting.workspace_id == ctx.workspace_id,
            Meeting.id == UUID(args["meeting_id"]),
        )
    )
    if not meeting:
        return {"error": "Meeting not found"}

    transcript = await ctx.db.scalar(
        select(Transcript).where(Transcript.meeting_id == meeting.id)
    )
    if not transcript:
        return {"error": "No transcript for this meeting"}

    extraction = await ctx.db.scalar(
        select(MeetingExtraction).where(MeetingExtraction.transcript_id == transcript.id)
    )
    if not extraction:
        return {"error": "No extraction available yet"}

    decisions = (await ctx.db.scalars(
        select(Decision).where(Decision.meeting_id == meeting.id)
    )).all()
    task_candidates = (await ctx.db.scalars(
        select(TaskCandidate).where(TaskCandidate.extraction_id == extraction.id)
    )).all()

    return {
        "status": extraction.status,
        "summary": extraction.summary,
        "decisions": [
            {"title": d.title, "rationale": d.rationale}
            for d in decisions
        ],
        "action_items": [
            {
                "ref": t.ref,
                "title": t.title,
                "owner_name": t.owner_name,
                "state": t.state.value if t.state else "pending",
                "confidence": t.confidence,
            }
            for t in task_candidates
        ],
    }


@tool(
    name="meeting_extract",
    description=(
        "Trigger AI extraction on a meeting transcript. This processes the "
        "transcript to identify decisions, action items, and risks. Tasks with "
        "high confidence are auto-approved. Use this after a meeting ends."
    ),
    parameters={
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string", "description": "Meeting UUID"},
        },
        "required": ["meeting_id"],
    },
)
async def meeting_extract(ctx, args: dict) -> dict:
    from uuid import UUID
    meeting = await ctx.db.scalar(
        select(Meeting).where(
            Meeting.workspace_id == ctx.workspace_id,
            Meeting.id == UUID(args["meeting_id"]),
        )
    )
    if not meeting:
        return {"error": "Meeting not found"}

    transcript = await ctx.db.scalar(
        select(Transcript).where(Transcript.meeting_id == meeting.id)
    )
    if not transcript:
        return {"error": "No transcript available for this meeting"}

    from ..services.meeting_extraction import run_extraction, ExtractionError
    try:
        extraction = await run_extraction(ctx.db, str(transcript.id))
        return {
            "status": extraction.status,
            "summary": extraction.summary,
            "message": "Extraction complete. Use meeting_get_extraction to see results.",
        }
    except ExtractionError as e:
        return {"error": f"Extraction failed: {e}"}
