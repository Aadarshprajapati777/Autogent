"""Slack onboarding service. After a workspace connects Slack, the agent
proactively DMs workspace members to collect their profile info (name, role,
skills, timezone). This builds people profiles automatically without the
founder having to manually enter everyone.

Flow:
1. List all Slack workspace members.
2. For each member that isn't a bot and hasn't been onboarded yet:
   a. Open a DM with them.
   b. Send an intro message asking them to share their role/skills.
   c. Create a Person record with their Slack info.
3. When they reply (via Slack events webhook), the agent processes their
   message and updates their profile.
"""
from __future__ import annotations

import logging
import uuid

import httpx
from sqlalchemy import select

from ..db.session import SessionLocal
from ..models.core import WorkspaceMember
from ..models.integrations import Integration, IntegrationProvider
from ..models.memory import Person, PersonRole
from ..services.integrations import get_integration_token

log = logging.getLogger(__name__)

INTRO_MESSAGE = (
    "Hi {name}! 👋 I'm Autogent, your team's AI project manager. "
    "I was just connected to this Slack workspace.\n\n"
    "To help your team work better, I'd like to know a bit about you:\n"
    "• What's your role on the team?\n"
    "• What are your main skills/technologies?\n"
    "• What timezone are you in?\n\n"
    "Just reply here and I'll keep your profile up to date. "
    "I'll use this to match you with the right tasks and check in on your work."
)


async def _slack_api(token: str, method: str, **params) -> dict:
    """Call a Slack Web API method."""
    url = f"https://slack.com/api/{method}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        if method.startswith("chat.postMessage") or "postMessage" in method:
            resp = await client.post(
                url, headers={"Authorization": f"Bearer {token}"}, json=params
            )
        else:
            resp = await client.post(
                url, headers={"Authorization": f"Bearer {token}"}, data=params
            )
        resp.raise_for_status()
        return resp.json()


async def start_slack_onboarding(workspace_id: uuid.UUID, integration_id: uuid.UUID) -> None:
    """Proactively DM all Slack workspace members to collect their info.
    Called as a fire-and-forget task after Slack OAuth completes."""
    log.info("Starting Slack onboarding for workspace %s", workspace_id)

    async with SessionLocal() as session:
        # Get the Slack token
        token = await get_integration_token(
            session, workspace_id, IntegrationProvider.SLACK
        )
        if not token:
            log.error("No Slack token found for workspace %s", workspace_id)
            return

        # List all workspace members
        result = await _slack_api(token, "users.list")
        if not result.get("ok"):
            log.error("Failed to list Slack users: %s", result.get("error"))
            return

        members = [
            m for m in result.get("members", [])
            if not m.get("is_bot") and not m.get("deleted") and m.get("id") != "USLACKBOT"
        ]
        log.info("Found %d non-bot members to onboard", len(members))

        # Get existing people to check who already has onboarding_completed
        existing = (
            await session.execute(
                select(Person).where(Person.workspace_id == workspace_id)
            )
        ).scalars().all()
        existing_by_slack_id = {p.slack_id: p for p in existing if p.slack_id}

        onboarded = 0
        for member in members:
            slack_id = member["id"]

            profile = member.get("profile", {})
            real_name = profile.get("real_name") or member.get("name", "there")
            email = profile.get("email")
            display_name = profile.get("display_name") or real_name
            avatar = profile.get("image_72") or profile.get("image_48")

            # Find or create the Person record
            person = existing_by_slack_id.get(slack_id)
            if person:
                # Person already exists — only send DM if onboarding not done yet
                if person.onboarding_completed:
                    log.info("Skipping %s — already onboarded", real_name)
                    continue
            else:
                # New person — create record
                person = Person(
                    workspace_id=workspace_id,
                    name=real_name,
                    email=email,
                    slack_id=slack_id,
                    slack_handle=member.get("name"),
                    avatar_url=avatar,
                    role=PersonRole.OTHER,
                    skills=[],
                    timezone=member.get("tz"),
                    onboarding_completed=False,
                )
                session.add(person)
                await session.flush()

            # Send the intro DM (to new people and existing un-onboarded people)
            try:
                dm = await _slack_api(token, "conversations.open", users=slack_id)
                if dm.get("ok") and dm.get("channel"):
                    channel_id = dm["channel"]["id"]
                    msg = await _slack_api(
                        token,
                        "chat.postMessage",
                        channel=channel_id,
                        text=INTRO_MESSAGE.format(name=display_name),
                    )
                    if msg.get("ok"):
                        onboarded += 1
                        log.info("Onboarded %s (%s)", real_name, slack_id)
                    else:
                        log.warning("Failed to send DM to %s: %s", real_name, msg.get("error"))
                else:
                    log.warning("Failed to open DM with %s: %s", real_name, dm.get("error"))
            except Exception as e:
                log.warning("Error onboarding %s: %s", real_name, e)

        await session.commit()
        log.info(
            "Slack onboarding complete for workspace %s: %d new people onboarded",
            workspace_id,
            onboarded,
        )
