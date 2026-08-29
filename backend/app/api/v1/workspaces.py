import re
import uuid
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...db.session import get_session
from ...models.core import MemberRole, Organization, User, Workspace, WorkspaceMember

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"


@router.get("")
async def list_workspaces(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = (
        await session.execute(
            select(Workspace, WorkspaceMember)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
            .order_by(Workspace.created_at.asc())
        )
    ).all()
    return {
        "count": len(rows),
        "workspaces": [
            {
                "id": str(ws.id),
                "name": ws.name,
                "slug": ws.slug,
                "role": member.role.value,
            }
            for ws, member in rows
        ],
    }


@router.post("")
async def create_workspace(
    body: WorkspaceCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Reuse the user's first org if they have one, else create one.
    org = (
        await session.execute(
            select(Organization)
            .join(Workspace, Workspace.organization_id == Organization.id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not org:
        slug = f"{_slugify(user.display_name)}-{str(user.id)[:8]}"
        org = Organization(name=f"{user.display_name}'s organization", slug=slug)
        session.add(org)
        await session.flush()

    ws = Workspace(
        organization_id=org.id,
        name=body.name,
        slug=f"{_slugify(body.name)}-{uuid.uuid4().hex[:6]}",
    )
    session.add(ws)
    await session.flush()
    session.add(
        WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=MemberRole.OWNER)
    )
    await session.commit()
    return {"id": str(ws.id), "name": ws.name, "slug": ws.slug, "role": "owner"}
