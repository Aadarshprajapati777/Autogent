"""Meetings endpoints. List meetings, create one (sends a Recall bot), and
view transcripts/extractions. The agent can also trigger extraction via its
tools, but the dashboard needs direct read access.
"""
import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...config import settings
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.meetings import Meeting, MeetingExtraction, MeetingProvider, MeetingStatus, Transcript

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
) -> dict:
    await _check_member(workspace_id, user, session)
    meetings = (await session.execute(
        select(Meeting)
        .where(Meeting.workspace_id == workspace_id)
        .order_by(desc(Meeting.created_at))
        .limit(100)
    )).scalars().all()
    return {
        "count": len(meetings),
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
