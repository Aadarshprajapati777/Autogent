"""Tasks dashboard endpoints. Read + update work tasks. Creation happens via
the agent's tasks_create tool, but the dashboard needs to list and update
them directly too.
"""
import uuid
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
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
) -> dict:
    await _check_member(workspace_id, user, session)
    stmt = (
        select(Task)
        .where(Task.workspace_id == workspace_id)
        .order_by(desc(Task.created_at))
        .limit(100)
    )
    if state:
        stmt = stmt.where(Task.state == TaskState(state))
    tasks = (await session.execute(stmt)).scalars().all()
    return {
        "count": len(tasks),
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
    state: str
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
    task.state = TaskState(body.state)
    task.last_activity_at = datetime.utcnow()
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
