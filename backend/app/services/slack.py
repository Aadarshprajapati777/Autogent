import hashlib, hmac, time
import httpx
from fastapi import HTTPException
from ..config import settings


class SlackClient:
    authorize_url = "https://slack.com/oauth/v2/authorize"
    scopes = "chat:write im:write im:history users:read users:read.email"

    async def access_token(self, code: str, redirect_uri: str) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/oauth.v2.access",
                data={
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": settings.slack_client_id,
                    "client_secret": settings.slack_client_secret,
                },
            )
            response.raise_for_status()
            data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "Slack OAuth failed"))
        return {
            "access_token": data["access_token"],
            "scope": data.get("scope", ""),
            "team": data.get("team", {}),
        }


def verify_slack(headers: dict[str, str], body: bytes) -> None:
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")
    if not timestamp or not signature or abs(time.time() - int(timestamp)) > 300:
        raise HTTPException(401, "Invalid Slack request")
    expected = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.encode(),
            f"v0:{timestamp}:".encode() + body,
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid Slack signature")
