"""Workspace members endpoints."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...db.session import get_session
from ...models.core import User, WorkspaceMember

router = APIRouter(prefix="/members", tags=["members"])


@router.get("")
async def list_members(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        raise HTTPException(403, "Not a member of this workspace")
    rows = (await session.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )).all()
    return {
        "count": len(rows),
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
