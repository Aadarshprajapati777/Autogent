"""Meeting transcript extraction.

Ingest a meeting transcript, extract decisions, action items, blockers, and
key discussion points. Store them as facts in memory via the extraction service.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.llm import LLMError, get_llm
from ..agent.parsing import parse_json_response
from ..agent.prompts import MEETING_SUMMARY_PROMPT
from .extraction import ingest_message

logger = logging.getLogger(__name__)


async def summarize_meeting(
    session: AsyncSession,
    workspace_id,
    transcript: str,
    participants: list[str],
    date: str | None = None,
    project: str | None = None,
) -> dict[str, Any]:
    """Summarize a meeting transcript and extract decisions + action items.

    Ingests the transcript and extracted items as facts so they become part
    of the PM's memory and feed into state inference.
    """
    started = time.perf_counter()
    meeting_date = date or datetime.now(timezone.utc).isoformat()

    prompt = MEETING_SUMMARY_PROMPT.format(
        transcript=transcript[:8000],
        date=meeting_date[:10],
        participants=", ".join(participants) or "Unknown",
    )

    try:
        response = await get_llm().complete(prompt, kind="meeting", max_tokens=1500)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Meeting summary payload is not an object")
    except Exception as exc:
        logger.exception("Meeting summary LLM failed: %s", exc)
        payload = {
            "summary": "Meeting summary generation failed. Transcript was ingested.",
            "decisions": [],
            "action_items": [],
            "blockers": [],
            "follow_ups": [],
            "participants": participants,
        }

    # Ingest participant lines as conversation facts
    for participant in participants:
        lines = [
            line for line in transcript.split("\n")
            if participant.lower() in line.lower()[:50]
        ]
        if lines:
            try:
                await ingest_message(
                    session, workspace_id,
                    speaker=participant, speaker_role="engineer",
                    message=" ".join(lines[:5]), channel="meeting", project=project,
                )
            except Exception:
                logger.warning("Failed to ingest lines for %s", participant)

    # Store decisions as facts
    for decision in payload.get("decisions") or []:
        decision_text = (
            f"{decision.get('subject', 'company')} decided: "
            f"{decision.get('value', '')}"
        )
        try:
            await ingest_message(
                session, workspace_id,
                speaker="meeting_summary", speaker_role="manager",
                message=decision_text, channel="meeting",
                project=decision.get("project") or project,
            )
        except Exception:
            logger.warning("Failed to ingest decision from meeting")

    # Store action items as commitment facts
    for action in payload.get("action_items") or []:
        person = action.get("person", "unknown")
        commitment_text = (
            f"{person} committed to: {action.get('commitment', '')}"
            + (f" by {action.get('due_date')}" if action.get("due_date") else "")
        )
        try:
            await ingest_message(
                session, workspace_id,
                speaker=person, speaker_role="engineer",
                message=commitment_text, channel="meeting",
                project=action.get("project") or project,
            )
        except Exception:
            logger.warning("Failed to ingest action item from meeting")

    # Store blockers
    for blocker in payload.get("blockers") or []:
        person = blocker.get("person", "unknown")
        blocker_text = f"{person} blocked by: {blocker.get('blocker', '')}"
        try:
            await ingest_message(
                session, workspace_id,
                speaker=person, speaker_role="engineer",
                message=blocker_text, channel="meeting",
                project=blocker.get("project") or project,
            )
        except Exception:
            logger.warning("Failed to ingest blocker from meeting")

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["meeting_date"] = meeting_date
    payload["participants"] = payload.get("participants") or participants
    payload["elapsed_ms"] = elapsed
    return payload
