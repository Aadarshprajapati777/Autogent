"""Meetings endpoints. List meetings, create one (sends a Recall bot), and
view transcripts/extractions. The agent can also trigger extraction via its
tools, but the dashboard needs direct read access.
"""
import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...api.pagination import pagination_params
from ...config import settings
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.meetings import (
    Meeting, MeetingExtraction, MeetingProvider, MeetingStatus,
    Speaker, Transcript, TranscriptChunk,
)
from ...models.work import CandidateState, Decision, TaskCandidate

router = APIRouter(prefix="/meetings", tags=["meetings"])


async def _check_member(workspace_id: uuid.UUID, user: User, session: AsyncSession) -> None:
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        raise HTTPException(403, "Not a member of this workspace")


@router.get("")
async def list_meetings(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination_params),
) -> dict:
    await _check_member(workspace_id, user, session)
    base_query = select(Meeting).where(Meeting.workspace_id == workspace_id)
    total = await session.scalar(select(func.count()).select_from(base_query.subquery()))
    meetings = (await session.execute(
        base_query.order_by(desc(Meeting.created_at)).offset(page["skip"]).limit(page["limit"])
    )).scalars().all()
    return {
        "count": len(meetings),
        "total": total,
        "skip": page["skip"],
        "limit": page["limit"],
        "has_more": (page["skip"] + len(meetings)) < (total or 0),
        "meetings": [
            {
                "id": str(m.id),
                "title": m.title,
                "provider": m.provider.value,
                "status": m.status.value,
                "scheduled_at": m.scheduled_at.isoformat() if m.scheduled_at else None,
                "started_at": m.started_at.isoformat() if m.started_at else None,
                "ended_at": m.ended_at.isoformat() if m.ended_at else None,
            }
            for m in meetings
        ],
    }


class CreateMeetingRequest(BaseModel):
    workspace_id: uuid.UUID
    join_url: str = Field(min_length=1)
    title: str | None = None
    provider: MeetingProvider = MeetingProvider.GOOGLE_MEET
    scheduled_at: datetime | None = None


@router.post("")
async def create_meeting(
    body: CreateMeetingRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(body.workspace_id, user, session)
    meeting = Meeting(
        workspace_id=body.workspace_id,
        provider=body.provider,
        join_url=body.join_url,
        title=body.title,
        scheduled_at=body.scheduled_at,
        status=MeetingStatus.SCHEDULED,
    )
    session.add(meeting)
    await session.flush()

    # Send a Recall bot if configured.
    if settings.recall_api_key:
        from ...services.recall_client import RecallClient, RecallAPIError
        try:
            bot = await RecallClient().create_bot(
                meeting_url=body.join_url,
                bot_name="Autogent",
                join_at=body.scheduled_at,
                metadata={"meeting_id": str(meeting.id), "workspace_id": str(body.workspace_id)},
            )
            meeting.recall_bot_id = bot.get("id")
            await session.flush()
        except RecallAPIError as exc:
            # Meeting is recorded; bot failure is non-fatal.
            pass

    await session.commit()
    return {
        "id": str(meeting.id),
        "title": meeting.title,
        "status": meeting.status.value,
        "recall_bot_id": meeting.recall_bot_id,
    }


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(workspace_id, user, session)
    meeting = await session.scalar(
        select(Meeting).where(Meeting.workspace_id == workspace_id, Meeting.id == meeting_id)
    )
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    transcript = await session.scalar(
        select(Transcript).where(Transcript.meeting_id == meeting.id)
    )
    extraction = None
    if transcript:
        extraction = await session.scalar(
            select(MeetingExtraction).where(MeetingExtraction.transcript_id == transcript.id)
        )
    return {
        "id": str(meeting.id),
        "title": meeting.title,
        "provider": meeting.provider.value,
        "status": meeting.status.value,
        "join_url": meeting.join_url,
        "scheduled_at": meeting.scheduled_at.isoformat() if meeting.scheduled_at else None,
        "transcript_status": transcript.status if transcript else None,
        "extraction": (
            {
                "status": extraction.status,
                "summary": extraction.summary,
                "confidence": extraction.confidence,
            }
            if extraction else None
        ),
    }


@router.get("/{meeting_id}/transcript")
async def get_meeting_transcript(
    meeting_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get the full transcript with speaker info for a meeting."""
    await _check_member(workspace_id, user, session)
    meeting = await session.scalar(
        select(Meeting).where(Meeting.workspace_id == workspace_id, Meeting.id == meeting_id)
    )
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    transcript = await session.scalar(
        select(Transcript).where(Transcript.meeting_id == meeting.id)
    )
    if not transcript:
        return {"chunks": [], "speakers": [], "status": None}

    speakers = (await session.scalars(
        select(Speaker).where(Speaker.meeting_id == meeting.id)
    )).all()
    speaker_map = {str(s.id): s.display_name for s in speakers}

    chunks = (await session.scalars(
        select(TranscriptChunk)
        .where(TranscriptChunk.transcript_id == transcript.id, TranscriptChunk.is_final.is_(True))
        .order_by(TranscriptChunk.sequence)
    )).all()

    return {
        "status": transcript.status,
        "speakers": [{"id": str(s.id), "name": s.display_name} for s in speakers],
        "chunks": [
            {
                "id": str(c.id),
                "speaker": speaker_map.get(str(c.speaker_id), "Unknown") if c.speaker_id else "Unknown",
                "text": c.text,
                "started_ms": c.started_ms,
                "ended_ms": c.ended_ms,
            }
            for c in chunks
        ],
    }


@router.get("/{meeting_id}/extraction")
async def get_meeting_extraction(
    meeting_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Get the extraction results (decisions, tasks, risks) for a meeting."""
    await _check_member(workspace_id, user, session)
    meeting = await session.scalar(
        select(Meeting).where(Meeting.workspace_id == workspace_id, Meeting.id == meeting_id)
    )
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    transcript = await session.scalar(
        select(Transcript).where(Transcript.meeting_id == meeting.id)
    )
    if not transcript:
        return {"status": None, "summary": None, "decisions": [], "tasks": [], "risks": []}

    extraction = await session.scalar(
        select(MeetingExtraction).where(MeetingExtraction.transcript_id == transcript.id)
    )
    if not extraction:
        return {"status": None, "summary": None, "decisions": [], "tasks": [], "risks": []}

    decisions = (await session.scalars(
        select(Decision).where(Decision.meeting_id == meeting.id)
    )).all()
    task_candidates = (await session.scalars(
        select(TaskCandidate).where(TaskCandidate.extraction_id == extraction.id)
    )).all()

    return {
        "status": extraction.status,
        "summary": extraction.summary,
        "confidence": extraction.confidence,
        "decisions": [
            {"title": d.title, "rationale": d.rationale, "confidence": d.confidence}
            for d in decisions
        ],
        "tasks": [
            {
                "ref": t.ref,
                "title": t.title,
                "description": t.description,
                "owner_name": t.owner_name,
                "state": t.state.value if t.state else "pending",
                "confidence": t.confidence,
                "due_at": t.due_at.isoformat() if t.due_at else None,
            }
            for t in task_candidates
        ],
    }
