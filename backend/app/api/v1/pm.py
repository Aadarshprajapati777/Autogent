"""PM intelligence API endpoints. Exposes the autonomous PM capabilities to
the frontend and operational workflows: onboarding, check-in, project
kickoff, PM decisions, work review, founder digest, and state inspection.
"""
from __future__ import annotations

import uuid
import time
from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent.llm import LLMError, get_llm
from ...agent.parsing import parse_json_response
from ...agent.prompts import (
    FOUNDER_DIGEST_PROMPT,
    PM_DECISION_PROMPT,
    WORK_REVIEW_PROMPT,
    NEXT_STEPS_PROMPT,
)
from ...api.deps import current_user, require_workspace_access
from ...db.session import get_session
from ...models.core import User
from ...models.memory import Fact, Person, TemporalStatus
from ...services.extraction import ingest_message
from ...services.pm_automation import (
    auto_check_in,
    auto_onboard_new_members,
    check_in_person,
    continue_onboarding,
    get_onboarding_status,
    kickoff_project,
    start_onboarding,
)
from ...services.state_inference import get_latest_states, infer_and_snapshot_state

router = APIRouter(prefix="/pm", tags=["pm"])


# ── Schemas ────────────────────────────────────────────────────────────────

class OnboardingStartRequest(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    role: str = "engineer"


class OnboardingContinueRequest(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=8000)


class CheckInRequest(BaseModel):
    workspace_id: uuid.UUID
    person: str | None = None  # if None, auto-detect


class KickoffRequest(BaseModel):
    workspace_id: uuid.UUID
    project_name: str


class DecisionRequest(BaseModel):
    workspace_id: uuid.UUID
    query: str = Field(min_length=1, max_length=4000)
    audience: str = Field("founder_non_technical",
                          description="founder_non_technical|founder_technical|engineer|internal")


class WorkReviewRequest(BaseModel):
    workspace_id: uuid.UUID
    engineer: str
    claim: str
    project: str | None = None


class IngestRequest(BaseModel):
    workspace_id: uuid.UUID
    speaker: str
    speaker_role: str = "other"
    message: str = Field(min_length=1, max_length=200_000)
    channel: str = "api"
    project: str | None = None


# ── Onboarding ─────────────────────────────────────────────────────────────

@router.post("/onboarding/start")
async def api_start_onboarding(
    body: OnboardingStartRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await start_onboarding(session, body.workspace_id, body.name, body.role)
    await session.commit()
    return result


@router.post("/onboarding/continue")
async def api_continue_onboarding(
    body: OnboardingContinueRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    status = await get_onboarding_status(session, body.workspace_id, body.name)
    if not status.get("started"):
        raise HTTPException(400, "Onboarding not started for this person")
    result = await continue_onboarding(
        session, body.workspace_id, body.name, body.message, status["step"],
    )
    await session.commit()
    return result


@router.get("/onboarding/status")
async def api_onboarding_status(
    workspace_id: uuid.UUID,
    name: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await get_onboarding_status(session, workspace_id, name)


@router.post("/onboarding/auto")
async def api_auto_onboard(
    body: OnboardingStartRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Auto-onboard all un-onboarded workspace members on Slack."""
    await require_workspace_access(body.workspace_id, user, session)
    results = await auto_onboard_new_members(session, body.workspace_id)
    await session.commit()
    return {"results": results}


# ── Check-in ───────────────────────────────────────────────────────────────

@router.post("/check-in")
async def api_check_in(
    body: CheckInRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    if body.person:
        result = await check_in_person(session, body.workspace_id, body.person)
        await session.commit()
        return result
    # Auto-detect who needs checking in
    results = await auto_check_in(session, body.workspace_id)
    await session.commit()
    return {"check_ins": results}


# ── Project kickoff ────────────────────────────────────────────────────────

@router.post("/kickoff")
async def api_kickoff(
    body: KickoffRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await kickoff_project(session, body.workspace_id, body.project_name)
    await session.commit()
    return result


# ── PM decision ────────────────────────────────────────────────────────────

@router.post("/decision")
async def api_pm_decision(
    body: DecisionRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    started = time.perf_counter()

    # Gather context: search memory, get states, build team summary
    states = await get_latest_states(session, body.workspace_id)

    # Search for relevant facts
    from ...agent.prompts import QUERY_INTENT_PROMPT
    facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == body.workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
        ).order_by(Fact.valid_from.desc()).limit(30)
    )).all()
    memory_context = "\n".join(
        f"- [{f.fact_kind.value}] {f.subject} {f.predicate} {f.value}"
        for f in facts
    ) or "(no facts in memory)"

    project_states = _format_project_states(states.get("projects", []))
    person_states = _format_person_states(states.get("people", []))

    # Build team summary from people
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == body.workspace_id)
    )).all()
    team_summary = "\n".join(
        f"- {p.name} ({p.role.value}): skills=[{', '.join(p.skills[:10])}]"
        + (f", {p.availability_hours_per_week} hrs/wk" if p.availability_hours_per_week else "")
        for p in people
    ) or "(no team members yet)"

    prompt = PM_DECISION_PROMPT.format(
        audience=body.audience,
        query=body.query,
        project_states=project_states,
        person_states=person_states,
        memory_context=memory_context[:2000],
        team_summary=team_summary,
    )

    try:
        response = await get_llm().complete(prompt, max_tokens=4000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Decision payload is not an object")
    except Exception as exc:
        payload = {
            "response_text": "I'm still learning about your team. Try asking me again in a moment.",
            "reasoning": f"LLM synthesis failed: {exc}",
            "suggested_actions": [{"action": "none", "target": "", "message": "", "urgency": "low"}],
            "risk_level": "medium",
        }

    elapsed = int((time.perf_counter() - started) * 1000)
    payload["query"] = body.query
    payload["audience"] = body.audience
    payload["elapsed_ms"] = elapsed
    return payload


# ── Work review ────────────────────────────────────────────────────────────

@router.post("/work-review")
async def api_work_review(
    body: WorkReviewRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    started = time.perf_counter()

    # Get the engineer's credibility from state snapshots
    states = await get_latest_states(session, body.workspace_id)
    person_state = next(
        (s for s in states.get("people", []) if s["entity_name"].lower() == body.engineer.lower()),
        None,
    )
    credibility = "unknown"
    credibility_score = 0.5
    if person_state:
        credibility = person_state.get("state", "unknown")
        credibility_score = person_state.get("score", 0.5)

    # Search for the original commitment
    facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == body.workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.subject) == body.engineer.lower(),
        ).order_by(Fact.valid_from.desc()).limit(10)
    )).all()

    original_commitment = "No specific commitment found matching this claim."
    for fact in facts:
        if fact.fact_kind.value == "commitment":
            original_commitment = f"{fact.subject} {fact.predicate} {fact.value}"
            if fact.due_date:
                original_commitment += f" (due: {fact.due_date[:10]})"
            break

    project_context = "\n".join(
        f"- [{f.fact_kind.value}] {f.predicate}: {f.value}" for f in facts[:8]
    ) or "No project context available."

    evidence = _extract_evidence(body.claim)

    prompt = WORK_REVIEW_PROMPT.format(
        engineer=body.engineer,
        claim=body.claim,
        evidence=evidence,
        credibility=f"{credibility} (score: {credibility_score})",
        commitment=original_commitment,
        project_context=project_context,
    )

    try:
        response = await get_llm().complete(prompt, max_tokens=1000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Work review payload is not an object")
    except Exception as exc:
        payload = {
            "assessment": "unverified",
            "confidence_in_claim": 0.3,
            "what_was_done": body.claim,
            "what_is_missing": "Unable to assess — LLM review failed.",
            "honest_review": f"I couldn't fully verify {body.engineer}'s claim.",
            "questions_for_engineer": ["Can you share more details about what you completed?"],
            "next_steps": ["Ask for specific evidence of completion"],
            "should_notify_founder": True,
            "founder_message": f"{body.engineer} reports they completed: {body.claim}. I haven't verified this yet.",
        }

    payload["engineer"] = body.engineer
    payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return payload


# ── Founder digest ─────────────────────────────────────────────────────────

@router.get("/digest")
async def api_founder_digest(
    workspace_id: uuid.UUID,
    audience: str = "founder_non_technical",
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    started = time.perf_counter()

    states = await get_latest_states(session, workspace_id)

    project_text = "\n".join(
        f"- {s['entity_name']}: {s['state']}, score {s['score']} — {s.get('summary', '')}"
        for s in states.get("projects", [])[:5]
    ) or "No project states available"

    person_text = "\n".join(
        f"- {s['entity_name']}: {s['state']}, score {s['score']} — {s.get('summary', '')}"
        for s in states.get("people", [])[:5]
    ) or "No person states available"

    # Get recent completions (status_update facts with completion words)
    completion_facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            Fact.fact_kind == "status_update" if hasattr(Fact.fact_kind, "value") else True,
        ).order_by(Fact.valid_from.desc()).limit(5)
    )).all()
    completions = "\n".join(
        f"- {f.subject} completed: {f.value}" for f in completion_facts
    ) or "No recent completions"

    prompt = FOUNDER_DIGEST_PROMPT.format(
        audience=audience,
        project_states=project_text,
        person_states=person_text,
        risks="No active risk tracking yet",
        completions=completions,
        decisions="No recent decisions tracked yet",
    )

    try:
        response = await get_llm().complete(prompt, max_tokens=800)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Digest payload is not an object")
    except Exception as exc:
        red_projects = [s for s in states.get("projects", [])
                        if s.get("state") in ("delayed", "blocked")]
        if red_projects:
            headline = f"{len(red_projects)} project(s) need your attention."
            urgency = "red"
        elif states.get("projects"):
            headline = "Projects are on track."
            urgency = "green"
        else:
            headline = "Not enough data to assess."
            urgency = "yellow"
        payload = {
            "headline": headline,
            "needs_attention": [],
            "going_well": [],
            "recommended_action": "Check in on at-risk projects" if red_projects else "Nothing needed right now",
            "urgency_level": urgency,
        }

    payload["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return payload


# ── State inspection ───────────────────────────────────────────────────────

@router.get("/state")
async def api_get_state(
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await get_latest_states(session, workspace_id)


@router.post("/state/infer")
async def api_infer_state(
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Manually trigger state inference for a workspace."""
    await require_workspace_access(workspace_id, user, session)
    result = await infer_and_snapshot_state(session, workspace_id)
    await session.commit()
    return result


# ── Ingest ─────────────────────────────────────────────────────────────────

@router.post("/ingest")
async def api_ingest(
    body: IngestRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Ingest a conversation message into memory with fact extraction."""
    await require_workspace_access(body.workspace_id, user, session)
    result = await ingest_message(
        session, body.workspace_id,
        speaker=body.speaker, speaker_role=body.speaker_role,
        message=body.message, channel=body.channel, project=body.project,
    )
    await session.commit()
    return result


# ── Helpers ────────────────────────────────────────────────────────────────

def _format_project_states(states: list[dict]) -> str:
    if not states:
        return "(no project states inferred yet)"
    lines = []
    for s in states:
        signals = "; ".join(s.get("risk_signals") or []) or "none"
        lines.append(
            f"- {s['entity_name']} [{s['state']}, score {s['score']}]: "
            f"{s.get('summary') or 'no summary'} (risks: {signals})"
        )
    return "\n".join(lines)


def _format_person_states(states: list[dict]) -> str:
    if not states:
        return "(no person states inferred yet)"
    lines = []
    for s in states:
        signals = "; ".join(s.get("risk_signals") or []) or "none"
        lines.append(
            f"- {s['entity_name']} [{s['state']}, score {s['score']}]: "
            f"{s.get('summary') or 'no summary'} (risks: {signals})"
        )
    return "\n".join(lines)


def _extract_evidence(claim: str) -> str:
    evidence_signals = []
    claim_lower = claim.lower()
    if "pr #" in claim_lower or "pull request" in claim_lower:
        evidence_signals.append("Mentions PR/pull request")
    if "deploy" in claim_lower or "shipped" in claim_lower or "live" in claim_lower:
        evidence_signals.append("Mentions deployment/shipping")
    if "test" in claim_lower:
        evidence_signals.append("Mentions tests")
    if any(c.isdigit() for c in claim):
        evidence_signals.append("Contains specific numbers")
    if "http" in claim_lower:
        evidence_signals.append("Contains URL")
    if not evidence_signals:
        return "No concrete evidence detected — claim is verbal only"
    return "; ".join(evidence_signals)
