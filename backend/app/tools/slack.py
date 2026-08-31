"""Slack tools. The agent can send messages, DM people, list channels, and
run check-ins. These require the Slack integration to be connected for the
workspace; if it isn't, the tool returns a clear error so the agent can tell
the user to connect Slack.
"""
from __future__ import annotations

import httpx

from ..agent.registry import tool
from ..models.integrations import IntegrationProvider
from ..services.integrations import get_integration_token


async def _slack_call(token: str, method: str, **params) -> dict:
    """Call a slack.com/api method. Returns the parsed JSON; raises on HTTP
    errors. Slack returns ok=false for API-level errors — callers check that."""
    url = f"https://slack.com/api/{method}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        if method.startswith("chat.postMessage") or "postMessage" in method:
            resp = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json=params)
        else:
            resp = await client.post(url, headers={"Authorization": f"Bearer {token}"}, data=params)
        resp.raise_for_status()
        return resp.json()


async def _resolve_token(ctx) -> str | None:
    return await get_integration_token(ctx.db, ctx.workspace_id, IntegrationProvider.SLACK)


@tool(
    name="slack_send_message",
    description=(
        "Send a message to a Slack channel or DM. Use channel (e.g. '#general' "
        "or a channel ID) or user (a user ID for a DM). Requires Slack to be "
        "connected."
    ),
    parameters={
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "Channel name or ID"},
            "text": {"type": "string"},
        },
        "required": ["channel", "text"],
    },
)
async def slack_send_message(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Slack is not connected for this workspace"}
    result = await _slack_call(token, "chat.postMessage", channel=args["channel"], text=args["text"])
    if not result.get("ok"):
        return {"error": result.get("error", "slack error")}
    return {"sent": True, "channel": result.get("channel"), "ts": result.get("ts")}


@tool(
    name="slack_list_channels",
    description="List public channels in the connected Slack workspace, showing which ones the bot has joined.",
    parameters={"type": "object", "properties": {}},
)
async def slack_list_channels(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Slack is not connected for this workspace"}
    result = await _slack_call(token, "conversations.list", types="public_channel", limit=100)
    if not result.get("ok"):
        return {"error": result.get("error", "slack error")}
    channels = [
        {
            "id": c["id"],
            "name": c["name"],
            "num_members": c.get("num_members", 0),
            "bot_joined": c.get("is_member", False),
        }
        for c in result.get("channels", [])
    ]
    return {"count": len(channels), "channels": channels}


@tool(
    name="slack_join_channel",
    description="Join a Slack channel so the bot can read messages and participate. Use this before reading messages from a channel the bot hasn't joined.",
    parameters={
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "Channel ID or name (e.g. 'general' or 'C01234')"},
        },
        "required": ["channel"],
    },
)
async def slack_join_channel(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Slack is not connected for this workspace"}
    channel = args["channel"]
    # If a name was given, resolve to an ID.
    if not channel.startswith("C"):
        listing = await _slack_call(token, "conversations.list", types="public_channel", limit=200)
        if listing.get("ok"):
            for c in listing.get("channels", []):
                if c["name"] == channel.lstrip("#"):
                    channel = c["id"]
                    break
    result = await _slack_call(token, "conversations.join", channel=channel)
    if not result.get("ok"):
        return {"error": result.get("error", "slack error")}
    return {"joined": True, "channel": channel, "name": result.get("channel", {}).get("name")}


@tool(
    name="slack_check_in",
    description=(
        "Send a check-in message to a person on Slack. Use this to proactively "
        "ask a team member for a status update on their work. Looks up the "
        "user by email or name and opens a DM."
    ),
    parameters={
        "type": "object",
        "properties": {
            "email": {"type": "string", "description": "Person's email (preferred)"},
            "name": {"type": "string", "description": "Fallback: person's name"},
            "message": {"type": "string", "description": "The check-in question"},
        },
        "required": ["message"],
    },
)
async def slack_check_in(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Slack is not connected for this workspace"}

    # Resolve a user ID by email, or by name via users.list.
    user_id = None
    if args.get("email"):
        lookup = await _slack_call(token, "users.lookupByEmail", email=args["email"])
        if lookup.get("ok") and lookup.get("user"):
            user_id = lookup["user"]["id"]
    if not user_id and args.get("name"):
        users = await _slack_call(token, "users.list")
        if users.get("ok"):
            target = args["name"].lower()
            for m in users.get("members", []):
                if m.get("name", "").lower() == target or target in m.get("real_name", "").lower():
                    user_id = m["id"]
                    break
    if not user_id:
        return {"error": "could not resolve Slack user"}

    # Open a DM and post the check-in.
    dm = await _slack_call(token, "conversations.open", users=user_id)
    if not dm.get("ok") or not dm.get("channel"):
        return {"error": dm.get("error", "could not open DM")}
    channel = dm["channel"]["id"]
    post = await _slack_call(token, "chat.postMessage", channel=channel, text=args["message"])
    if not post.get("ok"):
        return {"error": post.get("error", "slack error")}
    return {"sent": True, "user_id": user_id, "channel": channel, "ts": post.get("ts")}


@tool(
    name="slack_recent_messages",
    description=(
        "Read recent messages from a Slack channel. The bot will automatically "
        "join the channel if it hasn't already. Use channel ID or name (e.g. 'general')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "Channel ID or name"},
            "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
        },
        "required": ["channel"],
    },
)
async def slack_recent_messages(ctx, args: dict) -> dict:
    token = await _resolve_token(ctx)
    if not token:
        return {"error": "Slack is not connected for this workspace"}
    # If a name was given, resolve to an ID.
    channel = args["channel"]
    if not channel.startswith("C"):
        listing = await _slack_call(token, "conversations.list", types="public_channel", limit=200)
        if listing.get("ok"):
            for c in listing.get("channels", []):
                if c["name"] == channel.lstrip("#"):
                    channel = c["id"]
                    break

    # Auto-join the channel if not already a member — Slack requires
    # the bot to be in the channel to read conversations.history.
    join = await _slack_call(token, "conversations.join", channel=channel)
    if not join.get("ok"):
        # If join fails (e.g. private channel), surface the error
        return {"error": f"Cannot join channel: {join.get('error', 'unknown')}. Ask a member to invite the bot with /invite @Autogent"}

    history = await _slack_call(token, "conversations.history", channel=channel, limit=args.get("limit", 20))
    if not history.get("ok"):
        return {"error": history.get("error", "slack error")}
    msgs = [
        {"user": m.get("user"), "text": m.get("text", ""), "ts": m.get("ts")}
        for m in history.get("messages", [])
    ]
    return {"count": len(msgs), "messages": msgs}
