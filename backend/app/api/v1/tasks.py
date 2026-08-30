"""Tasks dashboard endpoints. Read + update work tasks. Creation happens via
the agent's tasks_create tool, but the dashboard needs to list and update
them directly too.
"""
import uuid
from datetime import datetime, UTC
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...api.pagination import pagination_params
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.work import Task, TaskComment, TaskState

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _check_member(workspace_id: uuid.UUID, user: User, session: AsyncSession) -> None:
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        raise HTTPException(403, "Not a member of this workspace")


@router.get("")
async def list_tasks(
    workspace_id: uuid.UUID = Query(...),
    state: str | None = Query(None),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination_params),
) -> dict:
    await _check_member(workspace_id, user, session)
    base = select(Task).where(Task.workspace_id == workspace_id)
    if state:
        try:
            state_enum = TaskState(state)
        except ValueError:
            raise HTTPException(422, f"Invalid state: {state}")
        base = base.where(Task.state == state_enum)
    total = await session.scalar(
        select(func.count()).select_from(base.subquery())
    )
    stmt = base.order_by(desc(Task.created_at)).offset(page["skip"]).limit(page["limit"])
    tasks = (await session.execute(stmt)).scalars().all()
    return {
        "count": len(tasks),
        "total": total,
        "skip": page["skip"],
        "limit": page["limit"],
        "has_more": (page["skip"] + len(tasks)) < (total or 0),
        "tasks": [
            {
                "id": str(t.id),
                "title": t.title,
                "state": t.state.value,
                "priority": t.priority,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "owner_id": str(t.owner_id) if t.owner_id else None,
                "last_activity_at": t.last_activity_at.isoformat() if t.last_activity_at else None,
            }
            for t in tasks
        ],
    }


@router.get("/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(workspace_id, user, session)
    task = await session.scalar(
        select(Task).where(Task.workspace_id == workspace_id, Task.id == task_id)
    )
    if not task:
        raise HTTPException(404, "Task not found")
    comments = (await session.execute(
        select(TaskComment).where(TaskComment.task_id == task.id).order_by(TaskComment.created_at)
    )).scalars().all()
    return {
        "id": str(task.id),
        "title": task.title,
        "description": task.description,
        "state": task.state.value,
        "priority": task.priority,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "confidence": task.confidence,
        "evidence": task.evidence,
        "comments": [
            {"id": str(c.id), "body": c.body, "author_id": str(c.author_id) if c.author_id else None,
             "created_at": c.created_at.isoformat() if c.created_at else None}
            for c in comments
        ],
    }


class TaskStateUpdate(BaseModel):
    state: TaskState
    workspace_id: uuid.UUID


@router.patch("/{task_id}/state")
async def update_task_state(
    task_id: uuid.UUID,
    body: TaskStateUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(body.workspace_id, user, session)
    task = await session.scalar(
        select(Task).where(Task.workspace_id == body.workspace_id, Task.id == task_id)
    )
    if not task:
        raise HTTPException(404, "Task not found")
    task.state = body.state
    task.last_activity_at = datetime.now(UTC)
    await session.commit()
    return {"id": str(task.id), "state": task.state.value}


class TaskCommentCreate(BaseModel):
    body: str
    workspace_id: uuid.UUID


@router.post("/{task_id}/comments")
async def add_comment(
    task_id: uuid.UUID,
    body: TaskCommentCreate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(body.workspace_id, user, session)
    task = await session.scalar(
        select(Task).where(Task.workspace_id == body.workspace_id, Task.id == task_id)
    )
    if not task:
        raise HTTPException(404, "Task not found")
    comment = TaskComment(task_id=task.id, author_id=user.id, body=body.body)
    session.add(comment)
    task.last_activity_at = datetime.utcnow()
    await session.commit()
    return {"id": str(comment.id), "task_id": str(task.id)}
