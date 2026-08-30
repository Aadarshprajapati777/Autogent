"""Approvals endpoints. Review task candidates extracted from meetings:
approve, edit, or reject them. Approved candidates become real tasks.
"""
import uuid
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...api.pagination import pagination_params
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.work import CandidateState, TaskCandidate
from ...services.approvals import ApprovalError, TaskApprovalService

router = APIRouter(prefix="/approvals", tags=["approvals"])


async def _check_member(workspace_id: uuid.UUID, user: User, session: AsyncSession) -> WorkspaceMember:
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        raise HTTPException(403, "Not a member of this workspace")
    return member


@router.get("")
async def list_candidates(
    workspace_id: uuid.UUID = Query(...),
    state: str | None = Query(None),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination_params),
) -> dict:
    await _check_member(workspace_id, user, session)
    base_query = select(TaskCandidate).where(TaskCandidate.workspace_id == workspace_id)
    if state:
        base_query = base_query.where(TaskCandidate.state == CandidateState(state))
    total = await session.scalar(select(func.count()).select_from(base_query.subquery()))
    stmt = base_query.order_by(desc(TaskCandidate.created_at)).offset(page["skip"]).limit(page["limit"])
    candidates = (await session.execute(stmt)).scalars().all()
    return {
        "count": len(candidates),
        "total": total,
        "skip": page["skip"],
        "limit": page["limit"],
        "has_more": (page["skip"] + len(candidates)) < (total or 0),
        "candidates": [
            {
                "id": str(c.id),
                "ref": c.ref,
                "title": c.title,
                "description": c.description,
                "owner_name": c.owner_name,
                "due_at": c.due_at.isoformat() if c.due_at else None,
                "confidence": c.confidence,
                "state": c.state.value,
                "task_id": str(c.task_id) if c.task_id else None,
            }
            for c in candidates
        ],
    }


class ReviewRequest(BaseModel):
    workspace_id: uuid.UUID
    decision: str  # approve | edit | reject
    edit: dict | None = None


@router.post("/{candidate_id}/review")
async def review_candidate(
    candidate_id: uuid.UUID,
    body: ReviewRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(body.workspace_id, user, session)
    service = TaskApprovalService()
    try:
        candidate = await service.review(session, candidate_id, body.decision, user.id, body.edit)
    except ApprovalError as exc:
        raise HTTPException(400, str(exc))
    return {
        "id": str(candidate.id),
        "state": candidate.state.value,
        "task_id": str(candidate.task_id) if candidate.task_id else None,
    }
