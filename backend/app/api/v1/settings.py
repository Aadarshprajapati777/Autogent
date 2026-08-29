"""Settings endpoints: escalation rules management."""
import uuid
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.operations import EscalationRule

router = APIRouter(prefix="/settings", tags=["settings"])


async def _require_admin(workspace_id: uuid.UUID, user: User, session: AsyncSession) -> None:
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member or member.role.value not in ("owner", "admin"):
        raise HTTPException(403, "Workspace admin access required")


@router.get("/escalations")
async def list_escalation_rules(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _require_admin(workspace_id, user, session)
    rules = (await session.execute(
        select(EscalationRule)
        .where(EscalationRule.workspace_id == workspace_id)
        .order_by(EscalationRule.priority)
    )).scalars().all()
    return {
        "count": len(rules),
        "rules": [
            {
                "id": str(r.id),
                "name": r.name,
                "enabled": r.enabled,
                "priority": r.priority,
                "conditions": r.conditions,
                "action": r.action,
            }
            for r in rules
        ],
    }


class EscalationRuleUpdate(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    priority: int | None = None
    conditions: dict | None = None
    action: dict | None = None


@router.patch("/escalations/{rule_id}")
async def update_escalation_rule(
    rule_id: uuid.UUID,
    body: EscalationRuleUpdate,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _require_admin(workspace_id, user, session)
    rule = await session.scalar(
        select(EscalationRule).where(
            EscalationRule.workspace_id == workspace_id,
            EscalationRule.id == rule_id,
        )
    )
    if not rule:
        raise HTTPException(404, "Rule not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    await session.commit()
    return {"id": str(rule.id), "updated": True}
