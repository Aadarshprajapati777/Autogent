"""Task scoring service. Calculates a 0-100 execution score for each task
based on real activity, deadlines, and confidence. The score reflects how
likely the task is to complete on time — high activity + no deadline pressure
= high score; stale + overdue = low score.

Factors:
  - Activity recency (0-30): how recently was last_activity_at updated
  - Deadline pressure (0-30): how much time is left vs overdue
  - State bonus (0-20): in_progress > open > blocked > overdue
  - Confidence (0-10): extraction confidence if available
  - Comment velocity (0-10): recent comments indicate active work
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.work import Task, TaskComment, TaskState


def _activity_score(last_activity: datetime | None, now: datetime) -> float:
    if not last_activity:
        return 5.0
    days = (now - last_activity.replace(tzinfo=UTC) if last_activity.tzinfo is None
            else now - last_activity).days
    if days <= 0:
        return 30.0
    if days <= 1:
        return 25.0
    if days <= 3:
        return 20.0
    if days <= 7:
        return 12.0
    if days <= 14:
        return 6.0
    return 2.0


def _deadline_score(due_at: datetime | None, now: datetime) -> float:
    if not due_at:
        return 20.0  # no deadline = neutral
    due = due_at.replace(tzinfo=UTC) if due_at.tzinfo is None else due_at
    days_left = (due - now).days
    if days_left > 7:
        return 30.0
    if days_left > 3:
        return 25.0
    if days_left > 0:
        return 18.0
    if days_left > -1:
        return 10.0
    if days_left > -3:
        return 5.0
    return 0.0


_STATE_BONUS = {
    TaskState.IN_PROGRESS: 20.0,
    TaskState.OPEN: 12.0,
    TaskState.BLOCKED: 5.0,
    TaskState.OVERDUE: 0.0,
    TaskState.COMPLETED: 20.0,
    TaskState.CANCELLED: 10.0,
}


def _confidence_score(confidence: float | None) -> float:
    if confidence is None:
        return 5.0
    return min(10.0, confidence * 10.0)


async def _comment_velocity_score(session: AsyncSession, task_id, now: datetime) -> float:
    week_ago = now - timedelta(days=7)
    count = await session.scalar(
        select(func.count(TaskComment.id)).where(
            TaskComment.task_id == task_id,
            TaskComment.created_at >= week_ago,
        )
    )
    if not count:
        return 0.0
    if count >= 5:
        return 10.0
    return min(10.0, count * 2.0)


async def score_task(session: AsyncSession, task: Task) -> float:
    now = datetime.now(UTC)
    score = (
        _activity_score(task.last_activity_at, now)
        + _deadline_score(task.due_at, now)
        + _STATE_BONUS.get(task.state, 10.0)
        + _confidence_score(task.confidence)
        + await _comment_velocity_score(session, task.id, now)
    )
    return round(min(100.0, max(0.0, score)), 1)


async def rescore_workspace_tasks(session: AsyncSession, workspace_id) -> int:
    """Recalculate execution_score for all non-completed tasks in a workspace.
    Returns the number of tasks updated."""
    tasks = (await session.scalars(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.state.notin_([TaskState.COMPLETED, TaskState.CANCELLED]),
        )
    )).all()
    updated = 0
    for task in tasks:
        new_score = await score_task(session, task)
        if task.execution_score != new_score:
            task.execution_score = new_score
            updated += 1
    if updated:
        await session.flush()
    return updated
