"""Resolve a person/task owner by name within a workspace. Tries users by
display name or email, then memory Person rows linked to a user. Returns a
User if matched, else None.
"""
from __future__ import annotations

import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.core import User
from ..models.memory import Person


async def resolve_owner(
    session: AsyncSession, workspace_id: uuid.UUID, name: str | None
) -> User | None:
    if not name:
        return None
    target = name.strip().lower()
    user = await session.scalar(
        select(User).where(func.lower(User.display_name) == target)
    )
    if user:
        return user
    user = await session.scalar(select(User).where(func.lower(User.email) == target))
    if user:
        return user
    person = await session.scalar(
        select(Person).where(
            Person.workspace_id == workspace_id,
            func.lower(Person.name) == target,
            Person.user_id.is_not(None),
        )
    )
    if person and person.user_id:
        return await session.get(User, person.user_id)
    return None
