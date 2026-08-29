"""Seed default escalation rules for a new workspace."""
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from ..models.operations import EscalationRule


async def seed_default_rules(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    defaults = [
        {
            "name": "Overdue high-priority tasks",
            "priority": 10,
            "conditions": {"state": "overdue", "priority_lte": 2},
            "action": {"notify": "manager", "channel": "slack"},
        },
        {
            "name": "Blocked tasks",
            "priority": 20,
            "conditions": {"state": "blocked"},
            "action": {"notify": "manager", "channel": "slack"},
        },
    ]
    for rule in defaults:
        session.add(EscalationRule(workspace_id=workspace_id, **rule))
    await session.flush()
