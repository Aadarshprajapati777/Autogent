"""Recall.ai webhook receiver. Recall sends Svix-signed webhooks when a bot
joins, leaves, or produces a transcript. This endpoint verifies the Svix
signature, matches the bot to a Meeting, ingests transcript chunks, and
triggers structured extraction.

In dev mode (no RECALL_SVIX_WEBHOOK_SECRET) the signature is skipped.
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import select

from ...config import settings
from ...db.session import SessionLocal
from ...models.meetings import (
    Meeting,
    MeetingExtraction,
    MeetingParticipant,
    MeetingStatus,
    Speaker,
    Transcript,
    TranscriptChunk,
)

router = APIRouter(prefix="/recall/webhooks", tags=["recall-webhooks"])
log = logging.getLogger(__name__)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def _ingest_transcript(meeting: Meeting, transcript_data: list[dict]) -> Transcript:
    """Persist transcript chunks from Recall's download format."""
    async with SessionLocal() as session:
        existing = await session.scalar(
            select(Transcript).where(Transcript.meeting_id == meeting.id)
        )
        if existing and existing.status == "completed":
            return existing
        transcript = existing or Transcript(
            meeting_id=meeting.id,
            status="capturing",
        )
        if not existing:
            session.add(transcript)
        await session.flush()

        # Build speaker map from Recall's speaker_id field.
        speaker_map: dict[str, Speaker] = {}
        for chunk in transcript_data:
            spk = chunk.get("speaker") or {}
            spk_id = str(spk.get("id") or spk.get("speaker_id") or "unknown")
            if spk_id not in speaker_map:
                display = spk.get("name") or spk.get("display_name") or f"Speaker {spk_id}"
                speaker = await session.scalar(
                    select(Speaker).where(
                        Speaker.meeting_id == meeting.id,
                        Speaker.provider_speaker_id == spk_id,
                    )
                )
                if not speaker:
                    speaker = Speaker(
                        meeting_id=meeting.id,
                        provider_speaker_id=spk_id,
                        display_name=display,
                    )
                    session.add(speaker)
                    await session.flush()
                speaker_map[spk_id] = speaker

        seq = 0
        for chunk in transcript_data:
            spk = chunk.get("speaker") or {}
            spk_id = str(spk.get("id") or spk.get("speaker_id") or "unknown")
            text = chunk.get("text") or chunk.get("content") or ""
            if not text.strip():
                continue
            utterance_id = str(chunk.get("id") or chunk.get("utterance_id") or f"u-{seq}")
            existing_chunk = await session.scalar(
                select(TranscriptChunk).where(
                    TranscriptChunk.transcript_id == transcript.id,
                    TranscriptChunk.provider_utterance_id == utterance_id,
                )
            )
            if existing_chunk:
                continue
            started = chunk.get("start") or chunk.get("start_ts") or chunk.get("started_ms")
            ended = chunk.get("end") or chunk.get("end_ts") or chunk.get("ended_ms")
            session.add(TranscriptChunk(
                transcript_id=transcript.id,
                speaker_id=speaker_map.get(spk_id, {}).get("id") if spk_id in speaker_map else None,
                provider_utterance_id=utterance_id,
                sequence=seq,
                text=text,
                started_ms=int(started) if started is not None else None,
                ended_ms=int(ended) if ended is not None else None,
                is_final=True,
                raw_payload=chunk,
            ))
            seq += 1

        transcript.status = "completed"
        await session.commit()
        return transcript


@router.post("")
async def recall_webhook(
    request: Request,
    svix_id: str | None = Header(None),
    svix_timestamp: str | None = Header(None),
    svix_signature: str | None = Header(None),
) -> Response:
    body = await request.body()

    # Svix signature verification (skipped in dev mode)
    if settings.recall_svix_webhook_secret and svix_signature:
        try:
            from svix.webhooks import Webhook
            wh = Webhook(settings.recall_svix_webhook_secret)
            wh.verify(
                body,
                {
                    "svix-id": svix_id or "",
                    "svix-timestamp": svix_timestamp or "",
                    "svix-signature": svix_signature,
                },
            )
        except Exception as exc:
            raise HTTPException(401, f"Invalid Svix signature: {exc}")
        payload = json.loads(body) if body else {}
    else:
        payload = json.loads(body) if body else {}

    event_type = payload.get("event") or payload.get("type") or ""
    data = payload.get("data") or payload.get("payload") or {}
    log.info("Recall webhook: %s", event_type)

    # Match bot to meeting via metadata or bot_id
    bot_id = data.get("bot_id") or data.get("id")
    metadata = data.get("metadata") or {}
    meeting_id_str = metadata.get("meeting_id")

    async with SessionLocal() as session:
        meeting = None
        if meeting_id_str:
            try:
                from uuid import UUID
                meeting = await session.scalar(
                    select(Meeting).where(Meeting.id == UUID(meeting_id_str))
                )
            except (ValueError, Exception):
                pass
        if not meeting and bot_id:
            meeting = await session.scalar(
                select(Meeting).where(Meeting.recall_bot_id == bot_id)
            )

        if not meeting:
            return Response(content='{"ok": true, "matched": false}', media_type="application/json")

        # Update meeting status based on event
        if event_type in ("bot.entered_waiting_room", "bot.entered_meeting", "bot.joined"):
            meeting.status = MeetingStatus.IN_PROGRESS
            meeting.started_at = _parse_iso(data.get("created_at")) or meeting.started_at
        elif event_type in ("bot.left_meeting", "bot.meeting_ended", "bot.end_of_meeting"):
            meeting.status = MeetingStatus.ENDED
            meeting.ended_at = _parse_iso(data.get("created_at")) or meeting.ended_at
        elif event_type == "bot.failed":
            meeting.status = MeetingStatus.FAILED
        await session.commit()

    # If a transcript is available, ingest and extract
    if event_type in ("bot.transcript.completed", "bot.meeting_ended", "bot.end_of_meeting"):
        from ...services.recall_client import RecallClient, RecallAPIError
        try:
            client = RecallClient()
            bot = await client.retrieve_bot(bot_id) if bot_id else {}
            url = client.transcript_download_url(bot)
            if url:
                chunks = await client.download_transcript(url)
                if chunks:
                    async with SessionLocal() as session:
                        meeting = await session.scalar(
                            select(Meeting).where(Meeting.recall_bot_id == bot_id)
                        )
                    if meeting:
                        transcript = await _ingest_transcript(meeting, chunks)
                        # Trigger extraction
                        from ...services.meeting_extraction import run_extraction, ExtractionError
                        async with SessionLocal() as session:
                            try:
                                await run_extraction(session, str(transcript.id))
                            except ExtractionError as exc:
                                log.warning("Extraction failed for meeting %s: %s", meeting.id, exc)
        except RecallAPIError as exc:
            log.warning("Recall API error during transcript fetch: %s", exc)
        except Exception as exc:
            log.exception("Recall webhook transcript processing failed: %s", exc)

    return Response(content='{"ok": true, "matched": true}', media_type="application/json")
