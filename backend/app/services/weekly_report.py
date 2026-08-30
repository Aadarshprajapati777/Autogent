"""Weekly report generation. Builds a human-readable summary of what shipped,
what slipped, and what needs the founder's attention. The report is stored as
a WeeklyReport row and optionally emailed to the workspace owner.
"""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.core import MemberRole, User, WorkspaceMember
from ..models.operations import Insight, WeeklyReport
from ..models.work import Task, TaskState

log = logging.getLogger(__name__)


async def generate_weekly_report(session: AsyncSession, workspace_id) -> WeeklyReport:
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)

    # Gather task stats for the week
    all_tasks = (await session.scalars(
        select(Task).where(Task.workspace_id == workspace_id)
    )).all()

    shipped = [t for t in all_tasks if t.state == TaskState.COMPLETED and t.last_activity_at and t.last_activity_at >= week_ago]
    slipped = [t for t in all_tasks if t.state != TaskState.COMPLETED and t.due_at and t.due_at < now]
    in_progress = [t for t in all_tasks if t.state == TaskState.IN_PROGRESS]
    blocked = [t for t in all_tasks if t.state == TaskState.BLOCKED]
    overdue = [t for t in all_tasks if t.state == TaskState.OVERDUE or (t.due_at and t.due_at < now and t.state not in (TaskState.COMPLETED, TaskState.CANCELLED))]

    # Low-score tasks need attention
    needs_attention = sorted(
        [t for t in all_tasks if t.execution_score < 40 and t.state not in (TaskState.COMPLETED, TaskState.CANCELLED)],
        key=lambda t: t.execution_score,
    )[:10]

    # Build the report data
    data = {
        "period": {"start": week_ago.isoformat(), "end": now.isoformat()},
        "summary": {
            "shipped_count": len(shipped),
            "slipped_count": len(slipped),
            "in_progress_count": len(in_progress),
            "blocked_count": len(blocked),
            "overdue_count": len(overdue),
        },
        "shipped": [
            {"title": t.title, "score": t.execution_score}
            for t in shipped
        ],
        "slipped": [
            {"title": t.title, "due_at": t.due_at.isoformat() if t.due_at else None}
            for t in slipped
        ],
        "needs_attention": [
            {"title": t.title, "score": t.execution_score, "state": t.state.value}
            for t in needs_attention
        ],
        "founder briefing": _build_briefing(shipped, slipped, blocked, overdue, needs_attention),
    }

    # Check if a report already exists for this period
    existing = await session.scalar(
        select(WeeklyReport).where(
            WeeklyReport.workspace_id == workspace_id,
            WeeklyReport.period_start >= week_ago.replace(hour=0, minute=0, second=0),
        )
    )
    if existing:
        existing.data = data
        existing.status = "completed"
        report = existing
    else:
        report = WeeklyReport(
            workspace_id=workspace_id,
            period_start=week_ago,
            data=data,
            status="completed",
        )
        session.add(report)
    await session.flush()

    # Create insights from the report
    if shipped:
        session.add(Insight(
            workspace_id=workspace_id,
            weekly_report_id=report.id,
            key="shipped_this_week",
            value={"count": len(shipped), "titles": [t.title for t in shipped[:5]]},
            confidence=0.9,
            explanation=f"{len(shipped)} tasks completed this week.",
        ))
    if overdue:
        session.add(Insight(
            workspace_id=workspace_id,
            weekly_report_id=report.id,
            key="overdue_tasks",
            value={"count": len(overdue), "titles": [t.title for t in overdue[:5]]},
            confidence=0.95,
            explanation=f"{len(overdue)} tasks are overdue and need attention.",
        ))
    if blocked:
        session.add(Insight(
            workspace_id=workspace_id,
            weekly_report_id=report.id,
            key="blocked_tasks",
            value={"count": len(blocked), "titles": [t.title for t in blocked[:5]]},
            confidence=0.9,
            explanation=f"{len(blocked)} tasks are blocked.",
        ))

    await session.commit()

    # Email the founder
    await _email_founder(session, workspace_id, data)

    return report


def _build_briefing(shipped, slipped, blocked, overdue, needs_attention) -> str:
    lines = []
    if shipped:
        lines.append(f"Shipped: {len(shipped)} task(s) completed this week.")
    if slipped:
        lines.append(f"Slipped: {len(slipped)} task(s) missed their deadline.")
    if blocked:
        lines.append(f"Blocked: {len(blocked)} task(s) need unblocking.")
    if overdue:
        lines.append(f"Overdue: {len(overdue)} task(s) are past due — review these first.")
    if needs_attention:
        lines.append(f"Needs attention: {len(needs_attention)} task(s) have low execution scores.")
    if not lines:
        lines.append("Everything is on track. No action needed this week.")
    return "\n".join(lines)


async def _email_founder(session: AsyncSession, workspace_id, data: dict) -> None:
    from ..config import settings
    if not settings.smtp_host:
        return
    # Find the workspace owner
    owner = await session.scalar(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == MemberRole.OWNER,
        )
    )
    if not owner or not owner.email:
        return
    try:
        from .email import send_email
        briefing = data.get("founder briefing", "Weekly report ready.")
        subject = "Your weekly Autogent report"
        send_email(
            to=owner.email,
            subject=subject,
            body=f"Hi {owner.display_name},\n\n{briefing}\n\nLog in to Autogent for the full report.",
        )
    except Exception:
        log.warning("Failed to email weekly report to founder")
