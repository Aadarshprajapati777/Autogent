"""Agent scheduler — runs the agent proactively on a schedule. Every cycle
it scans workspaces with Slack connected and asks the agent to check in
with team members and follow up on stale tasks. This is what makes Autogent
autonomous: it acts without a user prompt.

The scheduler also runs:
  - Task scoring (rescore all tasks weekly)
  - Escalation evaluation (fire rules for overdue/blocked tasks)
  - Weekly report generation (on the first cycle of each week)
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
    # 1. Run agent check-in cycles for workspaces with Slack connected
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Integration).where(
                    Integration.provider == IntegrationProvider.SLACK,
                    Integration.state == IntegrationState.CONNECTED,
                )
            )
        ).scalars().all()

    for integration in rows:
        workspace_id = integration.workspace_id
        try:
            async with SessionLocal() as session:
                ctx = ToolContext(db=session, workspace_id=workspace_id)
                await agent.run(
                    [
                        {
                            "role": "user",
                            "content": (
                                "Daily check-in cycle: review open tasks and "
                                "stale commitments in memory, then check in on Slack "
                                "with anyone who has overdue or blocked work. Ask "
                                "for: 1) status on current task, 2) any blockers, "
                                "3) ETA for completion. Keep messages short and "
                                "friendly. Don't ping anyone you already checked in "
                                "with today."
                            ),
                        }
                    ],
                    ctx,
                )
                await session.commit()
        except Exception as exc:
            logger.warning("Agent scheduler failed for %s: %s", workspace_id, exc)

    # 2. Rescore tasks for all workspaces
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

    # 3. Run escalation evaluation
    try:
        from ..services.escalation_engine import run_escalation_cycle
        await run_escalation_cycle()
    except Exception as exc:
        logger.warning("Escalation cycle failed: %s", exc)

    # 4. Generate weekly reports (check if it's a new week)
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
