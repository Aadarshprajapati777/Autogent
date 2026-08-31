"""People service — contribution profiles and reliability scoring.

Builds rich profiles from facts: what each person has done, their reliability
based on commitments vs completions, and a timeline of recent activity.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.memory import (
    Fact,
    FactKind,
    FactRelation,
    Person,
    TemporalStatus,
)

logger = logging.getLogger(__name__)


async def get_person(session: AsyncSession, workspace_id, name: str) -> dict[str, Any] | None:
    """Get a person's full profile including facts, reliability, contributions."""
    person = await session.scalar(
        select(Person).where(
            Person.workspace_id == workspace_id,
            func.lower(Person.name) == name.strip().lower(),
        )
    )
    if not person:
        return None

    facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.speaker) == name.strip().lower(),
        ).order_by(Fact.valid_from.desc()).limit(50)
    )).all()

    reliability = await compute_reliability(session, workspace_id, name)
    contributions = await get_contributions(session, workspace_id, name)

    return {
        "name": person.name,
        "role": person.role.value,
        "title": person.title,
        "skills": person.skills or [],
        "languages": person.languages or [],
        "is_technical": person.is_technical,
        "experience_years": person.experience_years,
        "availability_hours_per_week": person.availability_hours_per_week,
        "timezone": person.timezone,
        "interests": person.interests or [],
        "career_goals": person.career_goals,
        "resume_summary": person.resume_summary,
        "onboarding_step": person.onboarding_step,
        "onboarding_completed": person.onboarding_completed,
        "facts": [
            {
                "fact_id": f.fact_id,
                "fact_kind": f.fact_kind.value,
                "subject": f.subject,
                "predicate": f.predicate,
                "value": f.value,
                "valid_from": f.valid_from.isoformat() if f.valid_from else None,
                "project": f.project,
            }
            for f in facts
        ],
        "reliability": reliability,
        "contributions": contributions,
    }


async def compute_reliability(session: AsyncSession, workspace_id, name: str) -> dict[str, Any]:
    """Compute reliability score from commitment/completion/missed counts."""
    name_lower = name.strip().lower()
    rows = (await session.execute(
        select(Fact.fact_kind, func.count(Fact.id)).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.speaker) == name_lower,
            Fact.fact_kind.in_([FactKind.COMMITMENT, FactKind.STATUS_UPDATE, FactKind.PERFORMANCE]),
        ).group_by(Fact.fact_kind)
    )).all()
    counts = {row[0].value: int(row[1]) for row in rows}
    commitments = counts.get("commitment", 0)
    completed = counts.get("status_update", 0)
    missed = counts.get("performance", 0)
    total = commitments + completed + missed
    if total == 0:
        score = 0.5
    else:
        score = max(0.0, min(1.0, (completed + 0.5 * commitments - 2 * missed) / total))
    return {
        "commitments": commitments,
        "completed": completed,
        "missed_or_flagged": missed,
        "reliability_score": round(score, 2),
    }


async def list_people(session: AsyncSession, workspace_id) -> list[dict[str, Any]]:
    """List all people with reliability scores."""
    people = (await session.scalars(
        select(Person).where(Person.workspace_id == workspace_id).order_by(Person.name)
    )).all()
    summaries = []
    for person in people:
        reliability = await compute_reliability(session, workspace_id, person.name)
        summaries.append({
            "name": person.name,
            "role": person.role.value,
            "title": person.title,
            "skills": person.skills or [],
            "skill_count": len(person.skills or []),
            "commitment_count": reliability["commitments"],
            "completed_count": reliability["completed"],
            "missed_count": reliability["missed_or_flagged"],
            "reliability_score": reliability["reliability_score"],
            "availability_hours_per_week": person.availability_hours_per_week,
            "is_available": person.availability_hours_per_week is None or person.availability_hours_per_week > 0,
            "onboarding_completed": person.onboarding_completed,
        })
    return summaries


async def get_contributions(session: AsyncSession, workspace_id, name: str) -> dict[str, Any]:
    """Build a contribution profile — facts grouped by kind and project, with
    a timeline of recent activity and fulfilled commitment count."""
    name_lower = name.strip().lower()

    # Aggregate by fact kind
    kind_rows = (await session.execute(
        select(Fact.fact_kind, func.count(Fact.id)).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.speaker) == name_lower,
        ).group_by(Fact.fact_kind)
    )).all()
    by_kind = {row[0].value: int(row[1]) for row in kind_rows}

    # Aggregate by project
    project_rows = (await session.execute(
        select(Fact.project, func.count(Fact.id)).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.speaker) == name_lower,
            Fact.project.isnot(None),
        ).group_by(Fact.project)
    )).all()
    by_project = {row[0]: int(row[1]) for row in project_rows}

    # Recent timeline (last 20 facts)
    timeline_facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.speaker) == name_lower,
        ).order_by(Fact.valid_from.desc()).limit(20)
    )).all()
    timeline = [
        {
            "fact_kind": f.fact_kind.value,
            "value": f.value,
            "date": f.valid_from.isoformat() if f.valid_from else None,
            "project": f.project,
        }
        for f in timeline_facts
    ]

    # Count fulfilled commitments
    commitment_facts = (await session.scalars(
        select(Fact).where(
            Fact.workspace_id == workspace_id,
            Fact.temporal_status == TemporalStatus.CURRENT,
            func.lower(Fact.speaker) == name_lower,
            Fact.fact_kind == FactKind.COMMITMENT,
        )
    )).all()
    fulfilled_count = 0
    for commitment in commitment_facts:
        fulfilled = await session.scalar(
            select(FactRelation).where(
                FactRelation.workspace_id == workspace_id,
                FactRelation.from_fact_id == commitment.fact_id,
                FactRelation.relation_type == "fulfilled_by",
            )
        )
        if fulfilled:
            fulfilled_count += 1

    return {
        "total_facts": sum(by_kind.values()),
        "by_kind": by_kind,
        "by_project": by_project,
        "fulfilled_commitments": fulfilled_count,
        "timeline": timeline,
    }
