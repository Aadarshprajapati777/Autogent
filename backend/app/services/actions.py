from __future__ import annotations

import uuid as uuid_lib
from datetime import datetime, timezone

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.memory import ActionQueue


def _row_to_dict(row: ActionQueue) -> dict:
    return {
        "action_id": row.action_id,
        "action": row.action,
        "target": row.target,
        "message": row.message,
        "urgency": row.urgency,
        "status": row.status,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
    }


async def store_actions(
    session: AsyncSession, workspace_id: uuid_lib.UUID, actions: list[dict]
) -> list[dict]:
    created: list[dict] = []
    for action in actions:
        row = ActionQueue(
            workspace_id=workspace_id,
            action_id=f"action:{uuid_lib.uuid4().hex[:16]}",
            action=action.get("action", "none"),
            target=action.get("target", ""),
            message=action.get("message", ""),
            urgency=action.get("urgency", "low"),
            status="pending",
        )
        session.add(row)
        await session.flush()
        created.append(_row_to_dict(row))
    await session.commit()
    return created


async def list_actions(
    session: AsyncSession,
    workspace_id: uuid_lib.UUID,
    status: str = "pending",
    limit: int = 50,
) -> list[dict]:
    stmt = (
        select(ActionQueue)
        .where(ActionQueue.workspace_id == workspace_id, ActionQueue.status == status)
        .order_by(desc(ActionQueue.created_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [_row_to_dict(row) for row in result.scalars().all()]


async def complete_action(
    session: AsyncSession, workspace_id: uuid_lib.UUID, action_id: str
) -> dict | None:
    stmt = select(ActionQueue).where(
        ActionQueue.workspace_id == workspace_id, ActionQueue.action_id == action_id
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    row.status = "completed"
    row.completed_at = now
    await session.commit()
    return {
        "action_id": row.action_id,
        "status": row.status,
        "completed_at": row.completed_at,
    }
