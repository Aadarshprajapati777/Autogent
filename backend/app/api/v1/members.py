"""Workspace members endpoints."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...api.pagination import pagination_params
from ...db.session import get_session
from ...models.core import User, WorkspaceMember

router = APIRouter(prefix="/members", tags=["members"])


@router.get("")
async def list_members(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination_params),
) -> dict:
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        raise HTTPException(403, "Not a member of this workspace")
    base_query = (
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    total = await session.scalar(select(func.count()).select_from(base_query.subquery()))
    rows = (await session.execute(
        base_query.offset(page["skip"]).limit(page["limit"])
    )).all()
    return {
        "count": len(rows),
        "total": total,
        "skip": page["skip"],
        "limit": page["limit"],
        "has_more": (page["skip"] + len(rows)) < (total or 0),
        "members": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "display_name": u.display_name,
                "role": m.role.value,
                "avatar_url": u.avatar_url,
                "title": u.title,
            }
            for m, u in rows
        ],
    }
