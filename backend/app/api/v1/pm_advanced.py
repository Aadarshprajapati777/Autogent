"""Advanced PM API endpoints — planning, sprints, monitor, team, stakeholders,
decision history, actions, meetings, and people profiles.

These extend the core PM endpoints in pm.py with the full CloseLoopAI feature set.
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user, require_workspace_access
from ...db.session import get_session
from ...models.core import User
from ...services.context_engine import search_context
from ...services.decision_history import (
    decision_accuracy,
    list_decisions,
    record_outcome,
    store_decision,
)
from ...services.meetings import summarize_meeting
from ...services.monitor import (
    acknowledge_alert,
    escalate_stale_alerts,
    list_alerts,
    run_monitor_cycle,
)
from ...services.people import get_contributions, get_person, list_people
from ...services.planning import (
    analyze_dependencies,
    detect_scope_creep,
    estimation_accuracy,
    prioritize_tasks,
)
from ...services.sprints import (
    capacity_forecast,
    create_milestone,
    create_sprint,
    get_roadmap,
    get_sprint,
    list_milestones,
    list_sprints,
    plan_sprint,
    review_sprint,
)
from ...services.stakeholders import (
    generate_stakeholder_update,
    get_budget_status,
    record_spend,
    set_budget,
)
from ...services.team import generate_performance_feedback, sense_team_morale

router = APIRouter(prefix="/pm/advanced", tags=["pm-advanced"])


# ── Schemas ────────────────────────────────────────────────────────────────

class SprintCreateRequest(BaseModel):
    workspace_id: uuid.UUID
    project: str
    goal: str = Field(min_length=1)
    sprint_days: int = 14
    start_date: str | None = None


class MilestoneCreateRequest(BaseModel):
    workspace_id: uuid.UUID
    project: str
    title: str
    target_date: str
    description: str | None = None


class BudgetSetRequest(BaseModel):
    workspace_id: uuid.UUID
    project: str
    total_budget: float
    currency: str = "USD"
    start_date: str | None = None
    end_date: str | None = None


class SpendRecordRequest(BaseModel):
    workspace_id: uuid.UUID
    project: str
    amount: float
    category: str = "general"
    description: str | None = None


class StakeholderUpdateRequest(BaseModel):
    workspace_id: uuid.UUID
    stakeholder_type: str = "investor"
    project: str | None = None


class PerformanceFeedbackRequest(BaseModel):
    workspace_id: uuid.UUID
    engineer: str


class MeetingSummaryRequest(BaseModel):
    workspace_id: uuid.UUID
    transcript: str = Field(min_length=1, max_length=500_000)
    participants: list[str] = []
    date: str | None = None
    project: str | None = None


class OutcomeRecordRequest(BaseModel):
    workspace_id: uuid.UUID
    decision_id: str
    outcome: str
    notes: str = ""


class ContextSearchRequest(BaseModel):
    workspace_id: uuid.UUID
    query: str = Field(min_length=1, max_length=2000)
    max_facts: int = 20
    rerank: bool = True


# ── Context engine ─────────────────────────────────────────────────────────

@router.post("/context/search")
async def api_context_search(
    body: ContextSearchRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    return await search_context(
        session, body.workspace_id, body.query,
        max_facts=body.max_facts, rerank=body.rerank,
    )


# ── Planning ───────────────────────────────────────────────────────────────

@router.get("/planning/scope-creep")
async def api_scope_creep(
    workspace_id: uuid.UUID,
    project: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await detect_scope_creep(session, workspace_id, project)


@router.get("/planning/dependencies")
async def api_dependencies(
    workspace_id: uuid.UUID,
    project: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await analyze_dependencies(session, workspace_id, project)


@router.get("/planning/estimation-accuracy")
async def api_estimation_accuracy(
    workspace_id: uuid.UUID,
    person: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await estimation_accuracy(session, workspace_id, person)


@router.get("/planning/prioritize")
async def api_prioritize_tasks(
    workspace_id: uuid.UUID,
    project: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await prioritize_tasks(session, workspace_id, project)


# ── Sprints ────────────────────────────────────────────────────────────────

@router.post("/sprints")
async def api_create_sprint(
    body: SprintCreateRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await create_sprint(
        session, body.workspace_id, body.project, body.goal,
        body.sprint_days, body.start_date,
    )
    await session.commit()
    return result


@router.post("/sprints/{sprint_id}/plan")
async def api_plan_sprint(
    sprint_id: str,
    body: SprintCreateRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await plan_sprint(session, body.workspace_id, sprint_id)
    await session.commit()
    return result


@router.get("/sprints/{sprint_id}")
async def api_get_sprint(
    sprint_id: str,
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    result = await get_sprint(session, workspace_id, sprint_id)
    if not result:
        raise HTTPException(404, "Sprint not found")
    return result


@router.get("/sprints")
async def api_list_sprints(
    workspace_id: uuid.UUID,
    project: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    sprints = await list_sprints(session, workspace_id, project)
    return {"sprints": sprints, "count": len(sprints)}


@router.post("/sprints/{sprint_id}/review")
async def api_review_sprint(
    sprint_id: str,
    body: SprintCreateRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await review_sprint(session, body.workspace_id, sprint_id)
    await session.commit()
    return result


# ── Milestones ─────────────────────────────────────────────────────────────

@router.post("/milestones")
async def api_create_milestone(
    body: MilestoneCreateRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await create_milestone(
        session, body.workspace_id, body.project, body.title,
        body.target_date, body.description,
    )
    await session.commit()
    return result


@router.get("/milestones")
async def api_list_milestones(
    workspace_id: uuid.UUID,
    project: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    milestones = await list_milestones(session, workspace_id, project)
    return {"milestones": milestones, "count": len(milestones)}


@router.get("/roadmap")
async def api_roadmap(
    workspace_id: uuid.UUID,
    project: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await get_roadmap(session, workspace_id, project)


# ── Capacity ───────────────────────────────────────────────────────────────

@router.get("/capacity")
async def api_capacity_forecast(
    workspace_id: uuid.UUID,
    project: str | None = None,
    weeks: int = Query(2, ge=1, le=12),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await capacity_forecast(session, workspace_id, project, weeks)


# ── Monitor / Alerts ───────────────────────────────────────────────────────

@router.post("/monitor/run")
async def api_run_monitor(
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    result = await run_monitor_cycle(session, workspace_id)
    await session.commit()
    return result


@router.get("/alerts")
async def api_list_alerts(
    workspace_id: uuid.UUID,
    status: str = "open",
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    alerts = await list_alerts(session, workspace_id, status, limit)
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/alerts/{alert_id}/ack")
async def api_ack_alert(
    alert_id: str,
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    result = await acknowledge_alert(session, workspace_id, alert_id)
    if not result:
        raise HTTPException(404, "Alert not found or already acknowledged")
    await session.commit()
    return result


@router.post("/alerts/escalate")
async def api_escalate_alerts(
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    result = await escalate_stale_alerts(session, workspace_id)
    await session.commit()
    return result


# ── Team ───────────────────────────────────────────────────────────────────

@router.post("/team/performance-feedback")
async def api_performance_feedback(
    body: PerformanceFeedbackRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    return await generate_performance_feedback(session, body.workspace_id, body.engineer)


@router.get("/team/morale")
async def api_team_morale(
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await sense_team_morale(session, workspace_id)


# ── People ─────────────────────────────────────────────────────────────────

@router.get("/people")
async def api_list_people(
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    people = await list_people(session, workspace_id)
    return {"people": people, "count": len(people)}


@router.get("/people/{name}")
async def api_get_person(
    name: str,
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    person = await get_person(session, workspace_id, name)
    if not person:
        raise HTTPException(404, "Person not found")
    return person


@router.get("/people/{name}/contributions")
async def api_person_contributions(
    name: str,
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await get_contributions(session, workspace_id, name)


# ── Stakeholders ───────────────────────────────────────────────────────────

@router.post("/stakeholders/update")
async def api_stakeholder_update(
    body: StakeholderUpdateRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    return await generate_stakeholder_update(
        session, body.workspace_id, body.stakeholder_type, body.project,
    )


# ── Budget ─────────────────────────────────────────────────────────────────

@router.post("/budget")
async def api_set_budget(
    body: BudgetSetRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await set_budget(
        session, body.workspace_id, body.project, body.total_budget,
        body.currency, body.start_date, body.end_date,
    )
    await session.commit()
    return result


@router.post("/budget/spend")
async def api_record_spend(
    body: SpendRecordRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await record_spend(
        session, body.workspace_id, body.project, body.amount,
        body.category, body.description,
    )
    await session.commit()
    return result


@router.get("/budget")
async def api_budget_status(
    workspace_id: uuid.UUID,
    project: str | None = None,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await get_budget_status(session, workspace_id, project)


# ── Decision history ───────────────────────────────────────────────────────

@router.get("/decisions")
async def api_list_decisions(
    workspace_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    with_outcome_only: bool = False,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    decisions = await list_decisions(session, workspace_id, limit, with_outcome_only)
    return {"decisions": decisions, "count": len(decisions)}


@router.post("/decisions/outcome")
async def api_record_outcome(
    body: OutcomeRecordRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await record_outcome(
        session, body.workspace_id, body.decision_id, body.outcome, body.notes,
    )
    if not result:
        raise HTTPException(404, "Decision not found")
    await session.commit()
    return result


@router.get("/decisions/accuracy")
async def api_decision_accuracy(
    workspace_id: uuid.UUID,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(workspace_id, user, session)
    return await decision_accuracy(session, workspace_id)


# ── Meetings ───────────────────────────────────────────────────────────────

@router.post("/meetings/summarize")
async def api_meeting_summary(
    body: MeetingSummaryRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await require_workspace_access(body.workspace_id, user, session)
    result = await summarize_meeting(
        session, body.workspace_id, body.transcript,
        body.participants, body.date, body.project,
    )
    await session.commit()
    return result
