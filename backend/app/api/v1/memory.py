"""Memory dashboard endpoints. Read-only views of the in-backend memory store
so the frontend can show facts, people, and projects without going through
the agent. Writes happen via the agent's tools, except for people which can
also be added/edited directly from the UI for manual onboarding & CSV import.
"""
import uuid
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user, require_workspace_access
from ...api.pagination import pagination_params
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.memory import Fact, FactKind, Person, PersonRole, Project, TemporalStatus

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
    page: dict = Depends(pagination_params),
) -> dict:
    await _check_member(workspace_id, user, session)
    base = select(Fact).where(
        Fact.workspace_id == workspace_id,
        Fact.temporal_status == TemporalStatus.CURRENT,
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    facts = (
        await session.execute(
            base.order_by(desc(Fact.created_at)).offset(page["skip"]).limit(page["limit"])
        )
    ).scalars().all()
    return {
        "count": len(facts),
        "total": total,
        "skip": page["skip"],
        "limit": page["limit"],
        "has_more": (page["skip"] + len(facts)) < (total or 0),
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
    page: dict = Depends(pagination_params),
) -> dict:
    await _check_member(workspace_id, user, session)
    base = select(Person).where(Person.workspace_id == workspace_id)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    people = (
        await session.execute(
            base.offset(page["skip"]).limit(page["limit"])
        )
    ).scalars().all()
    return {
        "count": len(people),
        "total": total,
        "skip": page["skip"],
        "limit": page["limit"],
        "has_more": (page["skip"] + len(people)) < (total or 0),
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


class PersonUpsert(BaseModel):
    workspace_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    role: PersonRole = PersonRole.OTHER
    title: str | None = None
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    is_technical: bool = False
    experience_years: float | None = None
    availability_hours_per_week: float | None = None
    timezone: str | None = None
    interests: list[str] = Field(default_factory=list)
    career_goals: str | None = None
    resume_summary: str | None = None


@router.post("/people")
async def upsert_person(
    body: PersonUpsert,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create or update a person profile directly from the UI."""
    await _check_member(body.workspace_id, user, session)
    person = await session.scalar(
        select(Person).where(
            Person.workspace_id == body.workspace_id,
            func.lower(Person.name) == body.name.lower(),
        )
    )
    created = person is None
    if person is None:
        person = Person(
            workspace_id=body.workspace_id,
            name=body.name,
            role=body.role,
        )
        session.add(person)
        await session.flush()
    else:
        person.role = body.role

    for field in (
        "title", "skills", "languages", "is_technical",
        "experience_years", "availability_hours_per_week", "timezone",
        "interests", "career_goals", "resume_summary",
    ):
        val = getattr(body, field)
        if val is not None:
            setattr(person, field, val)
    await session.commit()
    return {
        "person_id": str(person.id),
        "name": person.name,
        "role": person.role.value,
        "created": created,
    }


class PersonBulkImport(BaseModel):
    workspace_id: uuid.UUID
    people: list[PersonUpsert]


@router.post("/people/bulk")
async def bulk_import_people(
    body: PersonBulkImport,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Bulk import people (e.g. from a parsed CSV in the frontend)."""
    await _check_member(body.workspace_id, user, session)
    created_count = 0
    updated_count = 0
    errors: list[dict] = []
    for idx, item in enumerate(body.people):
        if item.workspace_id != body.workspace_id:
            item = item.model_copy(update={"workspace_id": body.workspace_id})
        try:
            person = await session.scalar(
                select(Person).where(
                    Person.workspace_id == body.workspace_id,
                    func.lower(Person.name) == item.name.lower(),
                )
            )
            if person is None:
                person = Person(
                    workspace_id=body.workspace_id,
                    name=item.name,
                    role=item.role,
                )
                session.add(person)
                await session.flush()
                created_count += 1
            else:
                person.role = item.role
                updated_count += 1
            for field in (
                "title", "skills", "languages", "is_technical",
                "experience_years", "availability_hours_per_week", "timezone",
                "interests", "career_goals", "resume_summary",
            ):
                val = getattr(item, field)
                if val is not None:
                    setattr(person, field, val)
        except Exception as exc:
            errors.append({"row": idx, "name": item.name, "error": str(exc)})
    await session.commit()
    return {
        "created": created_count,
        "updated": updated_count,
        "errors": errors,
        "total": len(body.people),
    }


@router.delete("/people/{person_id}")
async def delete_person(
    person_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Delete a person profile from the UI."""
    await _check_member(workspace_id, user, session)
    person = await session.scalar(
        select(Person).where(
            Person.workspace_id == workspace_id,
            Person.id == person_id,
        )
    )
    if not person:
        raise HTTPException(404, "Person not found")
    await session.delete(person)
    await session.commit()
    return {"deleted": True, "person_id": str(person_id)}


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
    page: dict = Depends(pagination_params),
) -> dict:
    await _check_member(workspace_id, user, session)
    base = select(Project).where(Project.workspace_id == workspace_id)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    projects = (
        await session.execute(
            base.offset(page["skip"]).limit(page["limit"])
        )
    ).scalars().all()
    return {
        "count": len(projects),
        "total": total,
        "skip": page["skip"],
        "limit": page["limit"],
        "has_more": (page["skip"] + len(projects)) < (total or 0),
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
