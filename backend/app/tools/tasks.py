"""Task tools. The agent can create, update, list, and comment on work tasks.
These are the canonical execution tracker (work.Task), distinct from memory
facts. The agent extracts commitments from conversations and promotes them
into tasks here.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from ..agent.registry import tool
from ..models.memory import Person
from ..models.work import Task, TaskComment, TaskState


async def _resolve_owner(ctx, owner_name: str | None) -> uuid.UUID | None:
    if not owner_name:
        return None
    person = await ctx.db.scalar(
        select(Person).where(
            Person.workspace_id == ctx.workspace_id,
            func.lower(Person.name) == owner_name.lower(),
        )
    )
    return person.user_id if person and person.user_id else None


@tool(
    name="tasks_create",
    description=(
        "Create a tracked work task. Use when a commitment or action item is "
        "agreed on and should be followed up. The task gets an owner and due "
        "date if known."
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "owner_name": {"type": "string", "description": "Who will do it (name)"},
            "due_at": {"type": "string", "description": "ISO datetime"},
            "priority": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5},
        },
        "required": ["title"],
    },
)
async def tasks_create(ctx, args: dict) -> dict:
    task = Task(
        workspace_id=ctx.workspace_id,
        title=args["title"],
        description=args.get("description"),
        priority=args.get("priority", 3),
        state=TaskState.OPEN,
    )
    if args.get("owner_name"):
        task.owner_id = await _resolve_owner(ctx, args["owner_name"])
    if args.get("due_at"):
        try:
            task.due_at = datetime.fromisoformat(args["due_at"])
        except ValueError:
            pass
    ctx.db.add(task)
    await ctx.db.flush()
    return {"task_id": str(task.id), "title": task.title, "state": task.state.value, "owner_id": str(task.owner_id) if task.owner_id else None}


@tool(
    name="tasks_list",
    description="List tasks, optionally filtered by state or owner.",
    parameters={
        "type": "object",
        "properties": {
            "state": {
                "type": "string",
                "enum": [s.value for s in TaskState],
            },
            "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
        },
    },
)
async def tasks_list(ctx, args: dict) -> dict:
    stmt = (
        select(Task)
        .where(Task.workspace_id == ctx.workspace_id)
        .order_by(Task.created_at.desc())
        .limit(args.get("limit", 50))
    )
    if args.get("state"):
        stmt = stmt.where(Task.state == TaskState(args["state"]))
    tasks = (await ctx.db.scalars(stmt)).all()
    return {
        "count": len(tasks),
        "tasks": [
            {
                "task_id": str(t.id),
                "title": t.title,
                "state": t.state.value,
                "priority": t.priority,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "last_activity_at": t.last_activity_at.isoformat() if t.last_activity_at else None,
            }
            for t in tasks
        ],
    }


@tool(
    name="tasks_update_state",
    description="Update a task's state (e.g. mark in_progress or completed).",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "state": {"type": "string", "enum": [s.value for s in TaskState]},
        },
        "required": ["task_id", "state"],
    },
)
async def tasks_update_state(ctx, args: dict) -> dict:
    task = await ctx.db.scalar(
        select(Task).where(
            Task.workspace_id == ctx.workspace_id,
            Task.id == uuid.UUID(args["task_id"]),
        )
    )
    if not task:
        return {"error": "task not found"}
    task.state = TaskState(args["state"])
    task.last_activity_at = datetime.utcnow()
    await ctx.db.flush()
    return {"task_id": str(task.id), "state": task.state.value}


@tool(
    name="tasks_comment",
    description="Add a comment to a task (e.g. a status update or note).",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["task_id", "body"],
    },
)
async def tasks_comment(ctx, args: dict) -> dict:
    task = await ctx.db.scalar(
        select(Task).where(
            Task.workspace_id == ctx.workspace_id,
            Task.id == uuid.UUID(args["task_id"]),
        )
    )
    if not task:
        return {"error": "task not found"}
    comment = TaskComment(
        task_id=task.id,
        author_id=ctx.user_id,
        body=args["body"],
    )
    ctx.db.add(comment)
    task.last_activity_at = datetime.utcnow()
    await ctx.db.flush()
    return {"comment_id": str(comment.id), "task_id": str(task.id)}
