"""Agent scheduler — runs the agent proactively on a schedule. Every cycle
it scans workspaces with Slack connected and runs the autonomous PM jobs:
auto-onboarding, proactive check-ins, and project kickoff. This is what
makes Autogent autonomous: it acts without a user prompt.

The scheduler also runs:
  - Task scoring (rescore all tasks weekly)
  - Escalation evaluation (fire rules for overdue/blocked tasks)
  - Weekly report generation (on the first cycle of each week)
  - State inference (derive project/person state from recent facts)
"""
from __future__ import annotations

import asyncio
import logging
import os
import random

from sqlalchemy import select

from ..db.session import SessionLocal
from ..models.core import Workspace
from ..models.integrations import Integration, IntegrationProvider, IntegrationState
from ..agent.loop import agent
from ..agent.registry import ToolContext

logger = logging.getLogger(__name__)
_INTERVAL = int(os.environ.get("AGENT_SCHEDULER_INTERVAL_MINUTES", "30")) * 60
_task: asyncio.Task | None = None

import app.tools  # noqa: F401, E402


async def start_scheduler() -> None:
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_run_loop())
    logger.info("Agent scheduler started (interval=%ss)", _INTERVAL)


async def stop_scheduler() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
        logger.info("Agent scheduler stopped")


async def _run_loop() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await _run_once()
        except Exception as exc:
            logger.error("Agent scheduler error: %s", exc, exc_info=True)
        jitter = random.randint(-_INTERVAL // 5, _INTERVAL // 5)
        await asyncio.sleep(max(60, _INTERVAL + jitter))


async def _run_once() -> None:
    # Find workspaces with Slack connected
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Integration).where(
                    Integration.provider == IntegrationProvider.SLACK,
                    Integration.state == IntegrationState.CONNECTED,
                )
            )
        ).scalars().all()
        slack_workspaces = [r.workspace_id for r in rows]

    # 1. Auto-onboard new workspace members (PM automation)
    for workspace_id in slack_workspaces:
        try:
            async with SessionLocal() as session:
                from .pm_automation import auto_onboard_new_members
                results = await auto_onboard_new_members(session, workspace_id)
                await session.commit()
                onboarded = [r for r in results if r.get("action") == "onboarding_started"]
                if onboarded:
                    logger.info("Auto-onboarded %d members in workspace %s",
                                len(onboarded), workspace_id)
        except Exception as exc:
            logger.warning("Auto-onboarding failed for %s: %s", workspace_id, exc)

    # 2. Proactive check-ins (rate-limited, cooldown-aware)
    for workspace_id in slack_workspaces:
        try:
            async with SessionLocal() as session:
                from .pm_automation import auto_check_in
                results = await auto_check_in(session, workspace_id)
                await session.commit()
                checked_in = [r for r in results if r.get("needed") and not r.get("skipped")]
                if checked_in:
                    logger.info("Checked in with %d people in workspace %s",
                                len(checked_in), workspace_id)
        except Exception as exc:
            logger.warning("Auto check-in failed for %s: %s", workspace_id, exc)

    # 3. Project kickoff — auto-assign unassigned tasks and DM engineers
    for workspace_id in slack_workspaces:
        try:
            async with SessionLocal() as session:
                from sqlalchemy import func as sql_func
                from ..models.memory import Project
                projects = (await session.scalars(
                    select(Project).where(Project.workspace_id == workspace_id)
                )).all()
                from .pm_automation import kickoff_project
                for project in projects:
                    result = await kickoff_project(session, workspace_id, project.name)
                    if result.get("assigned", 0) > 0:
                        logger.info("Kicked off project %s: %d tasks assigned",
                                    project.name, result["assigned"])
                await session.commit()
        except Exception as exc:
            logger.warning("Project kickoff failed for %s: %s", workspace_id, exc)

    # 4. State inference — derive project/person state from recent facts
    for workspace_id in slack_workspaces:
        try:
            async with SessionLocal() as session:
                from .state_inference import infer_and_snapshot_state
                await infer_and_snapshot_state(session, workspace_id)
                await session.commit()
        except Exception as exc:
            logger.warning("State inference failed for %s: %s", workspace_id, exc)

    # 5. Monitor cycle — detect overdue commitments, silent engineers,
    #    single-points-of-failure, stale blockers. Escalate stale alerts.
    for workspace_id in slack_workspaces:
        try:
            async with SessionLocal() as session:
                from .monitor import run_monitor_cycle, escalate_stale_alerts
                monitor_result = await run_monitor_cycle(session, workspace_id)
                if monitor_result.get("alerts_generated", 0) > 0:
                    logger.info("Monitor: %d alerts in workspace %s",
                                monitor_result["alerts_generated"], workspace_id)
                esc_result = await escalate_stale_alerts(session, workspace_id)
                if esc_result.get("escalated_count", 0) > 0:
                    logger.info("Escalated %d stale alerts in workspace %s",
                                esc_result["escalated_count"], workspace_id)
                await session.commit()
        except Exception as exc:
            logger.warning("Monitor cycle failed for %s: %s", workspace_id, exc)

    # 6. Rescore tasks for all workspaces
    try:
        from ..services.task_scoring import rescore_workspace_tasks
        async with SessionLocal() as session:
            workspaces = (await session.scalars(select(Workspace))).all()
            for ws in workspaces:
                try:
                    updated = await rescore_workspace_tasks(session, ws.id)
                    if updated:
                        logger.info("Rescored %d tasks in workspace %s", updated, ws.id)
                except Exception:
                    logger.warning("Task scoring failed for workspace %s", ws.id)
            await session.commit()
    except Exception as exc:
        logger.warning("Task scoring cycle failed: %s", exc)

    # 7. Run escalation evaluation
    try:
        from ..services.escalation_engine import run_escalation_cycle
        await run_escalation_cycle()
    except Exception as exc:
        logger.warning("Escalation cycle failed: %s", exc)

    # 8. Generate weekly reports (check if it's a new week)
    try:
        from ..services.weekly_report import generate_weekly_report
        async with SessionLocal() as session:
            workspaces = (await session.scalars(select(Workspace))).all()
            for ws in workspaces:
                try:
                    await generate_weekly_report(session, ws.id)
                except Exception:
                    logger.warning("Weekly report failed for workspace %s", ws.id)
    except Exception as exc:
        logger.warning("Weekly report cycle failed: %s", exc)
