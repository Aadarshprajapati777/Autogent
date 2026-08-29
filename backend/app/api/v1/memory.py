"""Memory dashboard endpoints. Read-only views of the in-backend memory store
so the frontend can show facts, people, and projects without going through
the agent. Writes happen via the agent's tools.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user, require_workspace_access
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.memory import Fact, FactKind, Person, Project, TemporalStatus

router = APIRouter(prefix="/memory", tags=["memory"])


async def _check_member(
    workspace_id: uuid.UUID, user: User, session: AsyncSession
) -> WorkspaceMember:
    member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(403, "Not a member of this workspace")
    return member


@router.get("/facts")
async def list_facts(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(workspace_id, user, session)
    facts = (
        await session.execute(
            select(Fact)
            .where(
                Fact.workspace_id == workspace_id,
                Fact.temporal_status == TemporalStatus.CURRENT,
            )
            .order_by(desc(Fact.created_at))
            .limit(100)
        )
    ).scalars().all()
    return {
        "count": len(facts),
        "facts": [
            {
                "fact_id": f.fact_id,
                "subject": f.subject,
                "predicate": f.predicate,
                "value": f.value,
                "fact_kind": f.fact_kind.value,
                "topics": f.topics,
                "project": f.project,
                "speaker": f.speaker,
                "confidence": f.confidence,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in facts
        ],
    }


@router.get("/people")
async def list_people(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(workspace_id, user, session)
    people = (
        await session.execute(
            select(Person).where(Person.workspace_id == workspace_id)
        )
    ).scalars().all()
    return {
        "count": len(people),
        "people": [
            {
                "person_id": str(p.id),
                "name": p.name,
                "role": p.role.value,
                "title": p.title,
                "skills": p.skills,
                "is_technical": p.is_technical,
                "timezone": p.timezone,
            }
            for p in people
        ],
    }


@router.get("/people/{name}")
async def get_person(
    name: str,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(workspace_id, user, session)
    person = (
        await session.execute(
            select(Person).where(
                Person.workspace_id == workspace_id,
                func.lower(Person.name) == name.lower(),
            )
        )
    ).scalar_one_or_none()
    if not person:
        raise HTTPException(404, "Person not found")
    facts = (
        await session.execute(
            select(Fact)
            .where(
                Fact.workspace_id == workspace_id,
                Fact.temporal_status == TemporalStatus.CURRENT,
                func.lower(Fact.subject) == name.lower(),
            )
            .order_by(desc(Fact.created_at))
            .limit(50)
        )
    ).scalars().all()
    return {
        "name": person.name,
        "role": person.role.value,
        "title": person.title,
        "skills": person.skills,
        "languages": person.languages,
        "is_technical": person.is_technical,
        "experience_years": person.experience_years,
        "availability_hours_per_week": person.availability_hours_per_week,
        "timezone": person.timezone,
        "interests": person.interests,
        "career_goals": person.career_goals,
        "resume_summary": person.resume_summary,
        "recent_facts": [
            {"predicate": f.predicate, "value": f.value, "kind": f.fact_kind.value}
            for f in facts
        ],
    }


@router.get("/projects")
async def list_projects(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(workspace_id, user, session)
    projects = (
        await session.execute(
            select(Project).where(Project.workspace_id == workspace_id)
        )
    ).scalars().all()
    return {
        "count": len(projects),
        "projects": [
            {
                "project_id": str(p.id),
                "name": p.name,
                "status": p.status.value,
                "deadline": p.deadline,
                "description": p.description,
            }
            for p in projects
        ],
    }
