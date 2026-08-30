"""Escalation engine. Evaluates escalation rules for a workspace and fires
the appropriate action chain: Slack nudge → manager → founder. Each escalation
is recorded so we don't repeat the same level twice.

Rules are stored as EscalationRule rows with conditions (JSON) and action (JSON).
The engine matches conditions against task state and fires the action.
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from ..db.session import SessionLocal
from ..models.core import MemberRole, User, WorkspaceMember
from ..models.operations import Escalation, EscalationRule
from ..models.work import Task, TaskState

log = logging.getLogger(__name__)


def _matches_conditions(task: Task, conditions: dict) -> bool:
    state = conditions.get("state")
    if state and task.state.value != state:
        return False
    priority_lte = conditions.get("priority_lte")
    if priority_lte and task.priority > priority_lte:
        return False
    priority_gte = conditions.get("priority_gte")
    if priority_gte and task.priority < priority_gte:
        return False
    overdue_days = conditions.get("overdue_days")
    if overdue_days and task.due_at:
        due = task.due_at.replace(tzinfo=UTC) if task.due_at.tzinfo is None else task.due_at
        if (datetime.now(UTC) - due).days < overdue_days:
            return False
    return True


async def _get_escalation_level(session, task_id) -> int:
    """Return the highest escalation level already fired for this task."""
    rows = (await session.scalars(
        select(Escalation).where(
            Escalation.task_id == task_id,
            Escalation.resolved_at.is_(None),
        )
    )).all()
    return max((r.level for r in rows), default=0)


async def _get_workspace_members(session, workspace_id, role: MemberRole | None = None):
    stmt = (
        select(User, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id)
    )
    if role:
        stmt = stmt.where(WorkspaceMember.role == role)
    rows = (await session.execute(stmt)).all()
    return [(user, member) for user, member in rows]


async def _fire_escalation(
    session, task: Task, rule: EscalationRule, level: int
) -> None:
    action = rule.action or {}
    notify_target = action.get("notify", "manager")
    channel = action.get("channel", "slack")

    # Determine who to notify
    members = await _get_workspace_members(
        session, task.workspace_id,
        MemberRole.OWNER if notify_target == "founder"
        else MemberRole.ADMIN if notify_target == "manager"
        else None,
    )

    escalated_to = members[0][0].id if members else None

    # Send Slack notification if configured
    if channel == "slack" and members:
        from ..models.integrations import Integration, IntegrationProvider, IntegrationState
        from ..services.integrations import get_integration_token
        integration = await session.scalar(
            select(Integration).where(
                Integration.workspace_id == task.workspace_id,
                Integration.provider == IntegrationProvider.SLACK,
                Integration.state == IntegrationState.CONNECTED,
            )
        )
        if integration:
            token = await get_integration_token(
                session, task.workspace_id, IntegrationProvider.SLACK
            )
            if token:
                import httpx
                target_name = members[0][0].display_name
                msg = (
                    f"⚠️ Escalation (level {level}): Task '{task.title}' "
                    f"is {task.state.value}. Reason: {rule.name}. "
                    f"Please follow up."
                )
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        await client.post(
                            "https://slack.com/api/chat.postMessage",
                            headers={"Authorization": f"Bearer {token}"},
                            json={"channel": "#general", "text": msg},
                        )
                except Exception:
                    log.warning("Failed to send Slack escalation for task %s", task.id)

    # Record the escalation
    session.add(Escalation(
        task_id=task.id,
        escalated_to_id=escalated_to,
        level=level,
        reason=rule.name,
    ))


async def evaluate_workspace(session, workspace_id) -> int:
    """Run escalation rules for all tasks in a workspace. Returns the number
    of escalations fired."""
    rules = (await session.scalars(
        select(EscalationRule)
        .where(EscalationRule.workspace_id == workspace_id, EscalationRule.enabled.is_(True))
        .order_by(EscalationRule.priority.asc())
    )).all()
    if not rules:
        return 0

    tasks = (await session.scalars(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.state.notin_([TaskState.COMPLETED, TaskState.CANCELLED]),
        )
    )).all()

    fired = 0
    for task in tasks:
        current_level = await _get_escalation_level(session, task.id)
        for rule in rules:
            if not _matches_conditions(task, rule.conditions):
                continue
            next_level = current_level + 1
            if next_level > 3:
                break  # max escalation depth
            await _fire_escalation(session, task, rule, next_level)
            fired += 1
            break  # one rule per cycle

    if fired:
        await session.commit()
    return fired


async def run_escalation_cycle() -> None:
    """Run escalation evaluation for all workspaces. Called by the scheduler."""
    from ..models.core import Workspace
    async with SessionLocal() as session:
        workspaces = (await session.scalars(select(Workspace))).all()
        for ws in workspaces:
            try:
                count = await evaluate_workspace(session, ws.id)
                if count:
                    log.info("Escalated %d tasks in workspace %s", count, ws.id)
            except Exception:
                log.exception("Escalation failed for workspace %s", ws.id)
