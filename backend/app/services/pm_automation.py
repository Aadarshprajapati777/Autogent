"""Automated PM — the AI PM initiates and manages conversations with engineers
on Slack without manual triggering. Ported from CloseLoopAI, adapted to use
Autogent's in-backend memory (no separate kgmemory service).

Four autonomous capabilities:
1. Onboarding: structured 7-step conversation with new engineers on Slack.
2. Check-in: proactive reach-out to silent or at-risk engineers (rate-limited).
3. Kickoff: auto-assign unassigned tasks to best-matched engineers + DM them.
4. Reply handling: when an engineer replies to a DM, process their reply
   through fact extraction and generate a contextual PM response.
"""
from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.llm import LLMError, get_llm
from ..agent.parsing import parse_json_response
from ..agent.prompts import CHECKIN_PROMPT, ENGINEER_ONBOARDING_PROMPT, PM_DECISION_PROMPT
from ..models.core import ExternalIdentity, User, WorkspaceMember
from ..models.integrations import Integration, IntegrationProvider, IntegrationState, OAuthCredential
from ..models.memory import (
    CheckInRecord,
    Fact,
    FactKind,
    Person,
    PersonRole,
    Project,
    TemporalStatus,
)
from ..services.credentials import vault
from ..services.extraction import ingest_message
from ..services.state_inference import get_latest_states

logger = logging.getLogger(__name__)

# Thread tracking: maps slack_user_id -> thread_ts so PM replies in the same thread.
_thread_ts: dict[str, str] = {}

# Rate-limiting: (workspace_id, person_name) -> last check-in timestamp.
_last_check_in: dict[tuple[str, str], float] = {}
_CHECK_IN_COOLDOWN = 12 * 3600  # 12 hours

SILENCE_THRESHOLD_DAYS = 4

ONBOARDING_STEPS = [
    "role_experience", "skills", "past_projects",
    "availability", "interests", "work_style", "done",
]

INTAKE_STEPS = [
    "vision", "goals", "timeline", "team",
    "constraints", "priorities", "done",
]


# ── Slack helpers ──────────────────────────────────────────────────────────

async def get_slack_token(session: AsyncSession, workspace_id: uuid.UUID) -> str | None:
    integration = await session.scalar(
        select(Integration).where(
            Integration.workspace_id == workspace_id,
            Integration.provider == IntegrationProvider.SLACK,
            Integration.state == IntegrationState.CONNECTED,
        )
    )
    if not integration:
        return None
    cred = await session.scalar(
        select(OAuthCredential).where(OAuthCredential.integration_id == integration.id)
    )
    if not cred:
        return None
    return vault.decrypt(cred.access_token_encrypted)


async def send_dm(
    token: str, slack_user_id: str, text: str, thread_ts: str | None = None,
) -> dict:
    """Open a DM channel and post a message. Returns the Slack API response."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        dm = await client.post(
            "https://slack.com/api/conversations.open",
            headers={"Authorization": f"Bearer {token}"},
            data={"users": slack_user_id},
        )
        dm_data = dm.json()
        if not dm_data.get("ok"):
            return dm_data
        channel = dm_data["channel"]["id"]
        post_data: dict = {"channel": channel, "text": text}
        if thread_ts:
            post_data["thread_ts"] = thread_ts
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json=post_data,
        )
        return resp.json()


async def get_user_by_slack_id(
    session: AsyncSession, slack_user_id: str
) -> User | None:
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == "slack",
            ExternalIdentity.external_user_id == slack_user_id,
        )
    )
    if not identity:
        return None
    return await session.get(User, identity.user_id)


async def get_workspace_for_user(
    session: AsyncSession, user_id: uuid.UUID
) -> uuid.UUID | None:
    member = await session.scalar(
        select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
    )
    return member.workspace_id if member else None


async def get_slack_id_for_name(
    session: AsyncSession, workspace_id: uuid.UUID, name: str
) -> str | None:
    members = (await session.scalars(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    )).all()
    user_ids = [m.user_id for m in members]
    if not user_ids:
        return None
    users = (await session.scalars(
        select(User).where(User.id.in_(user_ids))
    )).all()
    name_lower = name.strip().lower()
    # Exact match first
    for user in users:
        if user.display_name and user.display_name.strip().lower() == name_lower:
            identity = await session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.provider == "slack",
                    ExternalIdentity.user_id == user.id,
                )
            )
            if identity:
                return identity.external_user_id
    # Partial match
    for user in users:
        if user.display_name and name_lower in user.display_name.strip().lower():
            identity = await session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.provider == "slack",
                    ExternalIdentity.user_id == user.id,
                )
            )
            if identity:
                return identity.external_user_id
    return None


# ── Onboarding ─────────────────────────────────────────────────────────────

async def start_onboarding(
    session: AsyncSession, workspace_id: uuid.UUID, name: str, role: str = "engineer",
) -> dict[str, Any]:
    """Start the onboarding conversation for a new engineer. Creates the person
    profile if needed, sets the onboarding step, and returns the first question."""
    person = await _upsert_person(session, workspace_id, name, role)
    person.onboarding_step = "role_experience"
    person.onboarding_completed = False
    await session.flush()

    result = await _generate_onboarding_response(
        session, workspace_id, name, "role_experience",
        conversation="", known_info="New engineer — no information yet.",
    )
    result["person"] = name
    result["step"] = "role_experience"
    return result


async def continue_onboarding(
    session: AsyncSession, workspace_id: uuid.UUID,
    name: str, message: str, current_step: str,
) -> dict[str, Any]:
    """Continue the onboarding conversation. The engineer has responded — we
    ingest their response (extracting facts), then let the LLM decide whether
    to advance or push back."""
    # Ingest the engineer's response to extract facts
    await ingest_message(
        session, workspace_id,
        speaker=name, speaker_role="engineer",
        message=message, channel="onboarding",
    )

    # Get what we know about this person
    known_info = await _format_known_info(session, workspace_id, name)
    conversation = await _format_conversation(session, workspace_id, name)
    covered_steps = _get_covered_steps(current_step)

    result = await _generate_onboarding_response(
        session, workspace_id, name, current_step,
        conversation=conversation, known_info=known_info,
        engineer_message=message, covered_steps=covered_steps,
    )

    actual_next_step = result.get("next_step", current_step)
    # Don't allow going backwards
    if actual_next_step in covered_steps and actual_next_step != current_step:
        actual_next_step = _next_step(current_step)

    # Update the person's onboarding step
    person = await session.scalar(
        select(Person).where(
            Person.workspace_id == workspace_id,
            func.lower(Person.name) == name.lower(),
        )
    )
    if person:
        person.onboarding_step = actual_next_step
        if actual_next_step == "done":
            person.onboarding_completed = True

    result["person"] = name
    result["step"] = actual_next_step
    return result


async def get_onboarding_status(
    session: AsyncSession, workspace_id: uuid.UUID, name: str,
) -> dict[str, Any]:
    """Check how far along an engineer is in the onboarding process."""
    person = await session.scalar(
        select(Person).where(
            Person.workspace_id == workspace_id,
            func.lower(Person.name) == name.lower(),
        )
    )
    if not person:
        return {"person": name, "started": False, "step": "not_started", "completed": False}

    step = person.onboarding_step or "not_started"
    completed = person.onboarding_completed or step == "done"
    return {
        "person": name,
        "started": person.onboarding_step is not None,
        "step": step,
        "completed": completed,
    }


async def _generate_onboarding_response(
    session: AsyncSession, workspace_id: uuid.UUID,
    name: str, step: str, conversation: str, known_info: str,
    engineer_message: str = "", covered_steps: list[str] | None = None,
) -> dict[str, Any]:
    prompt = ENGINEER_ONBOARDING_PROMPT.format(
        name=name,
        known_info=known_info,
        conversation=conversation or "(start of conversation)",
        step=step,
        engineer_message=engineer_message or "(no message yet — this is the first question)",
        covered_steps=", ".join(covered_steps) if covered_steps else "none",
    )
    try:
        response = await get_llm().complete(prompt, max_tokens=2000)
        payload = parse_json_response(response)
        if not isinstance(payload, dict):
            raise LLMError("Onboarding payload is not an object")
    except Exception as exc:
        logger.exception("Onboarding LLM failed: %s", exc)
        fallback_questions = {
            "role_experience": "What's your current role and how many years of experience?",
            "skills": "What technologies and tools are you most proficient in?",
            "past_projects": "Tell me about a recent project you worked on.",
            "availability": "How many hours per week can you commit, and what's your timezone?",
            "interests": "What kind of work excites you most?",
            "work_style": "How do you prefer to communicate and handle blockers?",
            "done": f"Got it, thanks {name}. That's all I needed.",
        }
        payload = {
            "next_step": step,
            "message": fallback_questions.get(step, "Can you tell me more about that?"),
            "extracted_facts": [],
        }
    return {
        "message": payload.get("message", ""),
        "next_step": payload.get("next_step", step),
        "extracted_facts": payload.get("extracted_facts") or [],
    }


# ── Check-in ───────────────────────────────────────────────────────────────

async def check_in_person(
    session: AsyncSession, workspace_id: uuid.UUID, person: str,
) -> dict[str, Any]:
    """Generate a proactive check-in message for a specific person."""
    signals = await _collect_person_signals(session, workspace_id, person)
    reason = _derive_check_in_reason(signals)
    if reason is None:
        return {
            "person": person, "needed": False,
            "message": f"No check-in needed for {person} — they're active and on track.",
            "check_in_message": None,
        }
    check_in = await _generate_check_in_message(person, reason, signals)
    check_in_msg = check_in.get("check_in_message", "")
    if check_in_msg:
        await _record_check_in(session, workspace_id, person, check_in_msg, reason)
    return {
        "person": person, "needed": True, "reason": reason,
        "check_in_message": check_in_msg,
        "tone": check_in.get("tone", "casual"),
        "specific_questions": check_in.get("specific_questions", []),
        "open_commitments": signals["commitments"],
        "days_since_last_seen": signals["days_since_last_seen"],
    }


async def auto_check_in(
    session: AsyncSession, workspace_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Auto-detect who needs checking in and generate messages for all of them.
    Rate-limited: each person is checked in at most once per 12 hours."""
    people = await _find_people_needing_check_in(session, workspace_id)
    if not people:
        return [{"action": "auto_check_in", "message": "No one needs checking in"}]

    ws_key = str(workspace_id)
    now = time.time()
    results = []
    for person_name, signals in people:
        reason = _derive_check_in_reason(signals)
        if reason is None:
            continue
        # Rate-limit check
        cooldown_key = (ws_key, person_name.lower())
        last = _last_check_in.get(cooldown_key)
        if last and (now - last) < _CHECK_IN_COOLDOWN:
            results.append({
                "person": person_name, "action": "check_in",
                "skipped": True,
                "reason": f"checked in {int((now - last) / 3600)}h ago",
            })
            continue

        check_in = await _generate_check_in_message(person_name, reason, signals)
        check_in_msg = check_in.get("check_in_message", "")
        if check_in_msg:
            await _record_check_in(session, workspace_id, person_name, check_in_msg, reason)

        # Deliver via Slack
        slack_id = await get_slack_id_for_name(session, workspace_id, person_name)
        slack_sent = False
        if slack_id:
            token = await get_slack_token(session, workspace_id)
            if token:
                try:
                    resp = await send_dm(token, slack_id, check_in_msg)
                    if resp.get("ok"):
                        slack_sent = True
                        _last_check_in[cooldown_key] = now
                        if resp.get("ts"):
                            _thread_ts[slack_id] = resp["ts"]
                except Exception as exc:
                    logger.warning("Failed to send check-in DM to %s: %s", person_name, exc)

        results.append({
            "person": person_name, "needed": True, "reason": reason,
            "check_in_message": check_in_msg,
            "slack_sent": slack_sent,
            "days_since_last_seen": signals["days_since_last_seen"],
        })
    return results


async def _collect_person_signals(
    session: AsyncSession, workspace_id: uuid.UUID, person: str,
) -> dict[str, Any]:
    facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.subject) == person.strip().lower(),
        ).order_by(Fact.valid_from.desc()).limit(30)
    )).all()

    commitments: list[dict] = []
    recent_facts: list[str] = []
    last_seen: datetime | None = None
    has_overdue = False
    now = datetime.now(timezone.utc)

    for fact in facts:
        if fact.fact_kind == FactKind.COMMITMENT:
            commitments.append({"value": fact.value, "due_date": fact.due_date})
            if fact.due_date:
                try:
                    due = datetime.fromisoformat(fact.due_date)
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    if due < now:
                        has_overdue = True
                except (ValueError, TypeError):
                    pass
        recent_facts.append(f"[{fact.fact_kind.value}] {fact.value}")
        if fact.valid_from and (last_seen is None or fact.valid_from > last_seen):
            last_seen = fact.valid_from

    # Get previous check-in messages
    prev = (await session.scalars(
        select(CheckInRecord).where(
            CheckInRecord.workspace_id == workspace_id,
            func.lower(CheckInRecord.person_name) == person.strip().lower(),
        ).order_by(CheckInRecord.created_at.desc()).limit(3)
    )).all()
    previous_checkins = [r.message for r in prev]

    days_since = _days_since(last_seen)
    return {
        "commitments": commitments,
        "recent_facts": recent_facts[:10],
        "last_seen": last_seen.isoformat() if last_seen else None,
        "days_since_last_seen": days_since,
        "has_overdue": has_overdue,
        "previous_checkins": previous_checkins,
    }


async def _find_people_needing_check_in(
    session: AsyncSession, workspace_id: uuid.UUID,
) -> list[tuple[str, dict[str, Any]]]:
    """Find people who need a check-in based on silence + open commitments."""
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == workspace_id)
    )).all()
    results = []
    for person in people:
        signals = await _collect_person_signals(session, workspace_id, person.name)
        reason = _derive_check_in_reason(signals)
        if reason:
            results.append((person.name, signals))
    return results


def _derive_check_in_reason(signals: dict[str, Any]) -> str | None:
    days = signals.get("days_since_last_seen")
    has_commitments = bool(signals.get("commitments"))
    has_overdue = signals.get("has_overdue", False)
    if has_overdue:
        return "has overdue commitments"
    if days is not None and days >= SILENCE_THRESHOLD_DAYS:
        if has_commitments:
            return f"has been silent for {days} days while having open commitments"
        return f"has been silent for {days} days — checking in to see how they're doing"
    if has_commitments and days is not None and days >= 2:
        return "has open commitments and hasn't provided a recent update"
    return None


async def _generate_check_in_message(
    person: str, reason: str, signals: dict[str, Any],
) -> dict[str, Any]:
    commitments_text = "; ".join(
        f"{c['value']} (due: {c['due_date'] or 'no date'})"
        for c in signals["commitments"][:5]
    ) or "(none)"
    recent_text = "\n".join(f"- {f}" for f in signals["recent_facts"][:5]) or "(no recent facts)"
    last_seen = signals.get("last_seen") or "never"
    prev_text = "\n".join(f"- {m}" for m in signals.get("previous_checkins", [])) or "(none)"

    prompt = CHECKIN_PROMPT.format(
        person=person, reason=reason,
        commitments=commitments_text, last_seen=last_seen,
        recent_facts=recent_text, previous_checkins=prev_text,
    )
    try:
        response = await get_llm().complete(prompt, max_tokens=600)
        payload = parse_json_response(response)
        if isinstance(payload, dict):
            return payload
    except (LLMError, ValueError) as exc:
        logger.warning("Check-in generation failed for %s: %s", person, exc)
    return {
        "check_in_message": (
            f"Hey {person}, I wanted to check in on your open commitments "
            f"({commitments_text}). Can you give me a concrete update?"
        ),
        "tone": "casual",
        "specific_questions": ["What's your current progress?", "Any blockers?"],
    }


async def _record_check_in(
    session: AsyncSession, workspace_id: uuid.UUID,
    person: str, message: str, reason: str | None = None,
) -> None:
    session.add(CheckInRecord(
        workspace_id=workspace_id,
        person_name=person,
        message=message[:200],
        reason=reason,
    ))
    await session.flush()


# ── Project kickoff ────────────────────────────────────────────────────────

async def kickoff_project(
    session: AsyncSession, workspace_id: uuid.UUID, project_name: str,
) -> dict[str, Any]:
    """Auto-assign unassigned tasks and DM engineers on Slack about them.
    Uses skill-matching from person profiles to find the best assignee."""
    from ..models.memory import MemoryTask, MemoryTaskStatus
    from ..models.work import Task, TaskState

    token = await get_slack_token(session, workspace_id)
    if not token:
        return {"project": project_name, "assigned": 0, "reached_out": 0, "error": "Slack not connected"}

    # Find the project
    project = await session.scalar(
        select(Project).where(
            Project.workspace_id == workspace_id,
            func.lower(Project.name) == project_name.lower(),
        )
    )
    if not project:
        return {"project": project_name, "assigned": 0, "reached_out": 0, "message": "Project not found"}

    # Find unassigned memory tasks for this project
    tasks = (await session.scalars(
        select(MemoryTask).where(
            MemoryTask.workspace_id == workspace_id,
            MemoryTask.project_id == project.id,
            MemoryTask.assignee_person_id.is_(None),
            MemoryTask.status.in_([MemoryTaskStatus.OPEN, MemoryTaskStatus.IN_PROGRESS]),
        )
    )).all()

    if not tasks:
        return {"project": project_name, "assigned": 0, "reached_out": 0, "message": "No unassigned tasks"}

    # Get all people with their skills for matching
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == workspace_id)
    )).all()

    assigned_count = 0
    reached_out = 0
    assignments: list[dict] = []

    for task in tasks:
        assignee = _find_best_match(task.required_skills, people)
        if not assignee:
            assignments.append({
                "task": task.title, "assignee": None,
                "error": "No matching engineer found",
            })
            continue

        task.assignee_person_id = assignee.id
        assigned_count += 1

        # Find the engineer's Slack ID
        slack_id = await get_slack_id_for_name(session, workspace_id, assignee.name)
        if not slack_id:
            assignments.append({
                "task": task.title, "assignee": assignee.name,
                "slack_sent": False, "error": "No Slack ID found",
            })
            continue

        dm_message = (
            f"Hey {assignee.name.split()[0]}, I've assigned you a task on the "
            f"'{project_name}' project: *{task.title}*. "
            f"Can you take a look and let me know when you can start?"
        )
        try:
            resp = await send_dm(token, slack_id, dm_message)
            if resp.get("ok"):
                reached_out += 1
                assignments.append({
                    "task": task.title, "assignee": assignee.name,
                    "slack_sent": True,
                })
            else:
                assignments.append({
                    "task": task.title, "assignee": assignee.name,
                    "slack_sent": False, "error": resp.get("error"),
                })
        except Exception as exc:
            assignments.append({
                "task": task.title, "assignee": assignee.name,
                "slack_sent": False, "error": str(exc),
            })

    await session.flush()
    return {
        "project": project_name,
        "assigned": assigned_count,
        "reached_out": reached_out,
        "assignments": assignments,
    }


def _find_best_match(required_skills: list[str], people: list[Person]) -> Person | None:
    """Find the person whose skills best match the required skills."""
    if not required_skills or not people:
        return people[0] if people else None
    required_lower = {s.lower() for s in required_skills}
    best = None
    best_score = -1
    for person in people:
        person_skills = {s.lower() for s in (person.skills or [])}
        overlap = len(required_lower & person_skills)
        # Consider availability — don't assign to someone with 0 hours
        avail = person.availability_hours_per_week or 0
        if avail == 0 and overlap > 0:
            continue
        score = overlap + (0.1 if avail and avail > 0 else 0)
        if score > best_score:
            best = person
            best_score = score
    return best


# ── Slack reply handling ───────────────────────────────────────────────────

async def process_slack_reply(
    session: AsyncSession,
    slack_user_id: str,
    message_text: str,
    thread_ts: str | None = None,
) -> dict[str, Any]:
    """Process an incoming Slack DM reply from an engineer.

    1. Identify the user and their workspace.
    2. Check if they're in an onboarding conversation.
    3. If onboarding: continue it, send the next question.
    4. If not: ingest their message, generate a contextual PM reply.
    """
    user = await get_user_by_slack_id(session, slack_user_id)
    if not user:
        return {"processed": False, "reason": "User not found"}

    workspace_id = await get_workspace_for_user(session, user.id)
    if not workspace_id:
        return {"processed": False, "reason": "No workspace for user"}

    token = await get_slack_token(session, workspace_id)
    if not token:
        return {"processed": False, "reason": "Slack not connected"}

    person_name = (user.display_name or "").split()[0] or user.display_name or "there"
    reply_thread_ts = thread_ts or _thread_ts.get(slack_user_id)

    # Check onboarding status
    onboarding = await get_onboarding_status(session, workspace_id, person_name)
    if onboarding.get("started") and not onboarding.get("completed"):
        current_step = onboarding.get("step", "role_experience")
        try:
            result = await continue_onboarding(
                session, workspace_id, person_name, message_text, current_step,
            )
        except Exception as exc:
            return {"processed": False, "reason": f"onboarding error: {exc}"}

        pm_message = result.get("message")
        if pm_message:
            try:
                resp = await send_dm(token, slack_user_id, pm_message, thread_ts=reply_thread_ts)
                if resp.get("ok") and resp.get("ts"):
                    _thread_ts[slack_user_id] = resp["ts"]
                return {
                    "processed": True, "action": "onboarding_continue",
                    "step": result.get("step"), "slack_sent": True,
                }
            except Exception as exc:
                return {
                    "processed": True, "action": "onboarding_continue",
                    "step": result.get("step"), "slack_sent": False, "error": str(exc),
                }
        return {"processed": True, "action": "onboarding_continue", "slack_sent": False}

    # Not in onboarding — ingest as a general update, then generate a reply
    try:
        await ingest_message(
            session, workspace_id,
            speaker=person_name, speaker_role="engineer",
            message=message_text, channel="slack",
        )
    except Exception as exc:
        logger.warning("Ingest failed for %s: %s", person_name, exc)
        return {"processed": False, "reason": "Ingest failed"}

    # Generate a contextual reply using the PM decision prompt
    reply_text = await _generate_contextual_reply(
        session, workspace_id, person_name, message_text,
    )

    try:
        await send_dm(token, slack_user_id, reply_text, thread_ts=reply_thread_ts)
    except Exception:
        pass

    return {"processed": True, "action": "ingest", "slack_sent": True}


async def _generate_contextual_reply(
    session: AsyncSession, workspace_id: uuid.UUID,
    person_name: str, message_text: str,
) -> str:
    """Generate a contextual PM reply to an engineer's Slack message."""
    # Gather context: person's facts, project states, team summary
    from ..services.state_inference import get_latest_states
    states = await get_latest_states(session, workspace_id)

    person_facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.subject) == person_name.lower(),
        ).order_by(Fact.valid_from.desc()).limit(10)
    )).all()

    memory_context = "\n".join(
        f"- [{f.fact_kind.value}] {f.predicate}: {f.value}" for f in person_facts
    ) or "(no facts)"

    project_states = "\n".join(
        f"- {s['entity_name']}: {s['state']}, {s.get('summary', '')}"
        for s in states.get("projects", [])[:3]
    ) or "(no project states)"

    person_states = "\n".join(
        f"- {s['entity_name']}: {s['state']}, {s.get('summary', '')}"
        for s in states.get("people", [])[:3]
    ) or "(no person states)"

    people = (await session.scalars(
        select(Person).where(Person.workspace_id == workspace_id)
    )).all()
    team_summary = "\n".join(
        f"- {p.name} ({p.role.value}): skills=[{', '.join(p.skills[:10])}]"
        for p in people
    ) or "(no team members)"

    prompt = PM_DECISION_PROMPT.format(
        audience="engineer",
        query=(
            f'The engineer {person_name} just sent this Slack message: '
            f'"{message_text}". '
            f'Respond naturally as their PM. Rules:\n'
            f"- If they're asking who you are, introduce yourself briefly as their AI PM.\n"
            f"- If they're saying hi or thanks, acknowledge briefly and ask about their current task.\n"
            f"- If they're giving an update, acknowledge it specifically and ask a follow-up if needed.\n"
            f"- If they're asking a question, answer it using what you know about the team and projects.\n"
            f"- If they're reporting a blocker, acknowledge and ask what they need.\n"
            f"- Keep it 1-3 sentences. Casual Slack tone. Don't be robotic.\n"
            f"- Don't start with 'Got it' or 'Great' every time. Vary your openers.\n"
            f"- Reference their actual work or skills when relevant.\n"
        ),
        team_summary=team_summary,
        project_states=project_states,
        person_states=person_states,
        memory_context=memory_context[:2000],
    )

    try:
        response = await get_llm().complete(prompt, max_tokens=500)
        payload = parse_json_response(response)
        if isinstance(payload, dict):
            text = payload.get("response_text", "")
            if text and len(text) <= 500:
                return text
    except Exception as exc:
        logger.warning("PM reply generation failed: %s", exc)

    # Fallback to varied acknowledgment
    fallbacks = [
        f"Thanks {person_name}, I noted that. What are you working on right now?",
        f"Got it. How's your current task going?",
        f"Thanks for the update. Anything blocking you?",
        f"Noted. What's your next step?",
        f"Okay. Keep me posted on how it goes.",
    ]
    return random.choice(fallbacks)


# ── Auto-onboard new members ───────────────────────────────────────────────

async def auto_onboard_new_members(
    session: AsyncSession, workspace_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Find workspace members who haven't been onboarded yet and start
    onboarding them automatically on Slack."""
    token = await get_slack_token(session, workspace_id)
    if not token:
        return [{"error": "Slack not connected"}]

    members = (await session.scalars(
        select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
    )).all()

    results = []
    for member in members:
        user = await session.get(User, member.user_id)
        if not user or not user.display_name:
            continue
        # Skip the owner
        if member.role.value == "owner":
            continue

        person_name = user.display_name.split()[0]

        # Check if already onboarded
        status = await get_onboarding_status(session, workspace_id, person_name)
        if status.get("started") and not status.get("completed"):
            continue  # In progress
        if status.get("completed"):
            continue

        # Find their Slack ID
        identity = await session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == "slack",
                ExternalIdentity.user_id == user.id,
            )
        )
        if not identity:
            continue

        # Start onboarding
        try:
            result = await start_onboarding(session, workspace_id, person_name, "engineer")
        except Exception as exc:
            results.append({"person": person_name, "error": str(exc)})
            continue

        pm_message = result.get("message")
        if pm_message:
            try:
                resp = await send_dm(token, identity.external_user_id, pm_message)
                if resp.get("ok") and resp.get("ts"):
                    _thread_ts[identity.external_user_id] = resp["ts"]
                results.append({
                    "person": person_name,
                    "slack_user_id": identity.external_user_id,
                    "action": "onboarding_started",
                    "slack_sent": True,
                })
            except Exception as exc:
                results.append({
                    "person": person_name,
                    "action": "onboarding_started",
                    "slack_sent": False, "error": str(exc),
                })
    return results


# ── Helpers ────────────────────────────────────────────────────────────────

def _next_step(current_step: str) -> str:
    if current_step in ONBOARDING_STEPS:
        idx = ONBOARDING_STEPS.index(current_step)
        if idx + 1 < len(ONBOARDING_STEPS):
            return ONBOARDING_STEPS[idx + 1]
    return "done"


def _get_covered_steps(current_step: str) -> list[str]:
    if current_step in ONBOARDING_STEPS:
        idx = ONBOARDING_STEPS.index(current_step)
        return ONBOARDING_STEPS[:idx]
    return []


def _days_since(last_seen) -> int | None:
    if not last_seen:
        return None
    from datetime import datetime, timezone
    if isinstance(last_seen, str):
        try:
            moment = datetime.fromisoformat(last_seen)
        except ValueError:
            return None
    else:
        moment = last_seen
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - moment).days)


async def _upsert_person(
    session: AsyncSession, workspace_id: uuid.UUID, name: str, role: str = "other",
) -> Person:
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
        person = Person(workspace_id=workspace_id, name=name, role=person_role)
        session.add(person)
        await session.flush()
    return person


async def _format_known_info(
    session: AsyncSession, workspace_id: uuid.UUID, name: str,
) -> str:
    person = await session.scalar(
        select(Person).where(
            Person.workspace_id == workspace_id,
            func.lower(Person.name) == name.lower(),
        )
    )
    if not person:
        return "No information yet."
    parts = []
    if person.role:
        parts.append(f"Role: {person.role.value}")
    if person.title:
        parts.append(f"Title: {person.title}")
    if person.skills:
        parts.append(f"Skills: {', '.join(person.skills)}")
    if person.languages:
        parts.append(f"Languages: {', '.join(person.languages)}")
    if person.experience_years:
        parts.append(f"Experience: {person.experience_years} years")
    if person.availability_hours_per_week:
        parts.append(f"Availability: {person.availability_hours_per_week} hrs/week")
    if person.timezone:
        parts.append(f"Timezone: {person.timezone}")
    facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.subject) == name.lower(),
        ).order_by(Fact.valid_from.desc()).limit(10)
    )).all()
    for f in facts:
        parts.append(f"- {f.fact_kind.value}: {f.predicate} {f.value}")
    return "\n".join(parts) if parts else "No information yet."


async def _format_conversation(
    session: AsyncSession, workspace_id: uuid.UUID, name: str,
) -> str:
    facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.subject) == name.lower(),
        ).order_by(Fact.valid_from.desc()).limit(20)
    )).all()
    if not facts:
        return "(start of conversation)"
    lines = []
    for f in facts:
        lines.append(f"- [{f.fact_kind.value}] {f.predicate}: {f.value}")
    return "\n".join(lines)
