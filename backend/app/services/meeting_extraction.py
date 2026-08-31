"""Meeting extraction: turn a transcript into decisions, tasks, risks, and
questions via structured LLM output. Cerebras is the default provider.
"""
import asyncio, json, logging
from dataclasses import dataclass
from datetime import UTC, datetime
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..schemas.extraction import MeetingExtractionResult
from ..services.directory import resolve_owner
from ..models.meetings import Meeting, MeetingExtraction, Speaker, Transcript, TranscriptChunk
from ..models.work import CandidateState, Decision, TaskCandidate

log = logging.getLogger(__name__)
SYSTEM_PROMPT = """You extract execution facts from meeting transcripts. Return only the required structured result.
Use only evidence explicitly supported by transcript chunks. Every decision, task, risk, and question needs one or more exact chunk IDs and short direct quotes. Do not invent owners, deadlines, dependencies, or risks. A missing field means unknown. Task refs must be T1, T2..., and dependencies must use those refs. Confidence is 0 to 1 and reflects evidence strength, not importance."""


class ExtractionError(RuntimeError):
    pass


_UNSUPPORTED_SCHEMA_KEYS = {
    "minLength", "maxLength", "pattern", "format", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems",
    "maxItems", "uniqueItems", "default",
}


def _strict_schema(schema: dict) -> dict:
    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node.setdefault("additionalProperties", False)
            for key in list(node.keys()):
                if key in _UNSUPPORTED_SCHEMA_KEYS:
                    del node[key]
                else:
                    walk(node[key])
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(schema)
    return schema


@dataclass(frozen=True)
class ChunkInput:
    id: str
    speaker: str | None
    text: str
    started_ms: int | None


def transcript_prompt(chunks: list[ChunkInput]) -> str:
    return (
        "Transcript chunks (the id values are the only valid evidence references):\n"
        + "\n".join(
            f"[{c.id}] speaker={c.speaker or 'Unknown'} time_ms={c.started_ms}: {c.text}"
            for c in chunks
        )
    )


class MeetingExtractionProvider:
    async def extract(self, chunks: list[ChunkInput]) -> MeetingExtractionResult:
        raise NotImplementedError


class OpenAIExtractionProvider(MeetingExtractionProvider):
    async def extract(self, chunks: list[ChunkInput]) -> MeetingExtractionResult:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": transcript_prompt(chunks)},
            ],
            response_format=MeetingExtractionResult,
        )
        parsed = response.choices[0].message.parsed
        if not parsed:
            raise ExtractionError("OpenAI returned no structured result")
        return parsed


class CerebrasExtractionProvider(MeetingExtractionProvider):
    async def extract(self, chunks: list[ChunkInput]) -> MeetingExtractionResult:
        def request() -> str:
            from cerebras.cloud.sdk import Cerebras
            client = Cerebras(api_key=settings.cerebras_api_key)
            response = client.chat.completions.create(
                model=settings.cerebras_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": transcript_prompt(chunks)},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "meeting_extraction",
                        "strict": True,
                        "schema": _strict_schema(MeetingExtractionResult.model_json_schema()),
                    },
                },
                max_completion_tokens=32768,
                temperature=0.1,
            )
            return response.choices[0].message.content or ""

        try:
            return MeetingExtractionResult.model_validate_json(await asyncio.to_thread(request))
        except (ValueError, json.JSONDecodeError) as error:
            raise ExtractionError("Cerebras returned malformed structured output") from error


def configured_provider() -> MeetingExtractionProvider:
    if settings.ai_provider == "gemini":
        return GeminiExtractionProvider()
    if settings.ai_provider == "cerebras":
        return CerebrasExtractionProvider()
    if settings.ai_provider == "openai":
        return OpenAIExtractionProvider()
    raise ExtractionError(f"Unsupported extraction provider: {settings.ai_provider}")


class GeminiExtractionProvider(MeetingExtractionProvider):
    """Uses Google Gemini (via Vertex AI or Gemini API) for structured meeting
    extraction."""
    async def extract(self, chunks: list[ChunkInput]) -> MeetingExtractionResult:
        from google import genai
        from google.genai import types as gtypes

        client = genai.Client(
            vertexai=settings.use_vertex_ai,
            project=settings.google_cloud_project if settings.use_vertex_ai else None,
            location=settings.google_cloud_location if settings.use_vertex_ai else None,
        )

        schema = _strict_schema(MeetingExtractionResult.model_json_schema())
        config = gtypes.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=schema,
        )

        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=f"{SYSTEM_PROMPT}\n\n{transcript_prompt(chunks)}",
            config=config,
        )
        text = response.text or ""
        if not text:
            raise ExtractionError("Gemini returned empty response")
        try:
            return MeetingExtractionResult.model_validate_json(text)
        except (ValueError, json.JSONDecodeError) as error:
            raise ExtractionError(f"Gemini returned malformed JSON: {text[:200]}") from error


async def extract_with_retry(
    provider: MeetingExtractionProvider, chunks: list[ChunkInput], attempts: int = 3
) -> MeetingExtractionResult:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            result = await provider.extract(chunks)
            valid_chunk_ids = {chunk.id for chunk in chunks}
            refs = [
                ref.chunk_id
                for item in [*result.decisions, *result.tasks, *result.risks, *result.questions]
                for ref in item.references
            ]
            if not set(refs).issubset(valid_chunk_ids):
                raise ExtractionError("Model referenced a chunk outside this transcript")
            return result
        except Exception as error:
            last_error = error
            log.warning("Meeting extraction attempt %s failed: %s", attempt + 1, type(error).__name__)
            if attempt < attempts - 1:
                await asyncio.sleep(2 ** attempt)
    raise ExtractionError("Meeting extraction retry budget exhausted") from last_error


async def run_extraction(session: AsyncSession, transcript_id: str) -> MeetingExtraction:
    transcript = await session.get(Transcript, transcript_id)
    if not transcript:
        raise ExtractionError("Transcript not found")
    extraction = await session.scalar(
        select(MeetingExtraction).where(MeetingExtraction.transcript_id == transcript.id)
    )
    if extraction and extraction.status == "completed":
        return extraction

    rows_with_speakers = (
        await session.execute(
            select(TranscriptChunk, Speaker)
            .outerjoin(Speaker, Speaker.id == TranscriptChunk.speaker_id)
            .where(TranscriptChunk.transcript_id == transcript.id, TranscriptChunk.is_final.is_(True))
            .order_by(TranscriptChunk.sequence)
        )
    ).all()
    if not rows_with_speakers:
        raise ExtractionError("Transcript has no final chunks")

    chunks = [
        ChunkInput(str(row.id), speaker.display_name if speaker else None, row.text, row.started_ms)
        for row, speaker in rows_with_speakers
    ]

    if not extraction:
        extraction = MeetingExtraction(
            transcript_id=transcript.id,
            provider=settings.ai_provider,
            model=(
                settings.gemini_model if settings.ai_provider == "gemini"
                else settings.cerebras_model if settings.ai_provider == "cerebras"
                else "gpt-4o-mini"
            ),
        )
        session.add(extraction)
    extraction.status = "processing"
    await session.commit()

    try:
        result = await extract_with_retry(configured_provider(), chunks)
    except Exception as error:
        extraction.status, extraction.error = "failed", str(error)
        await session.commit()
        raise

    meeting = await session.get(Meeting, transcript.meeting_id)
    if not meeting:
        raise ExtractionError("Meeting not found")

    for decision in result.decisions:
        session.add(Decision(
            workspace_id=meeting.workspace_id,
            meeting_id=meeting.id,
            title=decision.title,
            rationale=decision.rationale,
            confidence=decision.confidence,
            source_chunk_ids=[r.model_dump() for r in decision.references],
        ))

    candidates: list[TaskCandidate] = []
    for item in result.tasks:
        owner = await resolve_owner(session, meeting.workspace_id, item.owner_name)
        candidate = TaskCandidate(
            workspace_id=meeting.workspace_id,
            extraction_id=extraction.id,
            ref=item.ref,
            title=item.title,
            description=item.description,
            owner_id=owner.id if owner else None,
            owner_name=item.owner_name,
            due_at=item.deadline,
            confidence=item.confidence,
            evidence=[r.model_dump() for r in item.references],
            dependency_refs=item.dependency_refs,
            state=(
                CandidateState.AUTO_APPROVED
                if item.confidence >= 0.85
                else CandidateState.PENDING
            ),
        )
        session.add(candidate)
        candidates.append(candidate)
    await session.flush()

    # Auto-approve high-confidence candidates into real tasks.
    from ..services.approvals import TaskApprovalService
    approvals = TaskApprovalService()
    for candidate in candidates:
        if candidate.state == CandidateState.AUTO_APPROVED:
            await approvals.materialize(session, candidate)
    for candidate in candidates:
        if candidate.task_id:
            await approvals.materialize_dependencies(session, candidate)

    extraction.status = "completed"
    extraction.summary = result.meeting_summary
    extraction.confidence = result.confidence
    extraction.result = result.model_dump(mode="json")
    extraction.error = None
    await session.commit()
    return extraction
