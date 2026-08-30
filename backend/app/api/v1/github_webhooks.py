"""GitHub webhook receiver. Ingests push/PR events into GithubActivity rows
and matches them to tasks by title/branch references. Signature verification
uses HMAC-SHA256 with the GitHub webhook secret.
"""
import hashlib, hmac, json, logging, re
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import select

from ...config import settings
from ...db.session import SessionLocal
from ...models.integrations import GithubActivity, GithubRepo, Integration, IntegrationProvider
from ...models.webhooks import WebhookEvent
from ...models.work import Task, TaskActivityMatch

router = APIRouter(prefix="/github/webhooks", tags=["github-webhooks"])
log = logging.getLogger(__name__)


def _verify(payload: bytes, signature: str) -> bool:
    if not settings.github_webhook_secret:
        return True  # dev mode
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# Match task references like #42, TASK-42, or [task-id] in commit/PR text.
_TASK_REF_RE = re.compile(r"(?:#|TASK-)(\d+)|\[task[:\s-]+([a-f0-9-]+)\]", re.IGNORECASE)


def _extract_task_refs(text: str) -> list[str]:
    refs = []
    for match in _TASK_REF_RE.finditer(text or ""):
        ref = match.group(1) or match.group(2)
        if ref:
            refs.append(ref)
    return refs


async def _process_push_event(payload: dict, repo: GithubRepo | None) -> None:
    async with SessionLocal() as session:
        if not repo:
            return
        commits = payload.get("commits", [])
        pusher = payload.get("pusher", {}).get("name")
        for commit in commits:
            sha = commit.get("id") or commit.get("sha")
            if not sha:
                continue
            existing = await session.scalar(
                select(GithubActivity).where(
                    GithubActivity.repo_id == repo.id,
                    GithubActivity.external_id == sha,
                )
            )
            if existing:
                continue
            activity = GithubActivity(
                repo_id=repo.id,
                external_id=sha,
                activity_type="push",
                occurred_at=datetime.utcnow(),
                payload={
                    "message": commit.get("message"),
                    "author": commit.get("author", {}).get("name"),
                    "pusher": pusher,
                    "url": commit.get("url"),
                },
            )
            session.add(activity)
            await session.flush()

            # Match to tasks by commit message references
            refs = _extract_task_refs(commit.get("message", ""))
            for ref in refs:
                task = await _find_task_by_ref(session, repo, ref)
                if task:
                    session.add(TaskActivityMatch(
                        task_id=task.id,
                        github_activity_id=activity.id,
                        confidence=0.9,
                        reason=f"commit message references #{ref}",
                    ))
                    task.last_activity_at = datetime.utcnow()
        await session.commit()


async def _process_pr_event(payload: dict, repo: GithubRepo | None, action: str) -> None:
    async with SessionLocal() as session:
        if not repo:
            return
        pr = payload.get("pull_request", {})
        pr_number = str(pr.get("number", ""))
        if not pr_number:
            return
        external_id = f"pr-{pr_number}"
        existing = await session.scalar(
            select(GithubActivity).where(
                GithubActivity.repo_id == repo.id,
                GithubActivity.external_id == external_id,
            )
        )
        if existing:
            activity = existing
            activity.payload = {
                "action": action,
                "title": pr.get("title"),
                "body": pr.get("body"),
                "state": pr.get("state"),
                "merged": pr.get("merged"),
                "user": pr.get("user", {}).get("login"),
                "url": pr.get("html_url"),
            }
        else:
            activity = GithubActivity(
                repo_id=repo.id,
                external_id=external_id,
                activity_type="pull_request",
                occurred_at=datetime.utcnow(),
                payload={
                    "action": action,
                    "title": pr.get("title"),
                    "body": pr.get("body"),
                    "state": pr.get("state"),
                    "merged": pr.get("merged"),
                    "user": pr.get("user", {}).get("login"),
                    "url": pr.get("html_url"),
                },
            )
            session.add(activity)
            await session.flush()

        # Match to tasks by PR title/body references
        refs = _extract_task_refs((pr.get("title") or "") + " " + (pr.get("body") or ""))
        for ref in refs:
            task = await _find_task_by_ref(session, repo, ref)
            if task:
                existing_match = await session.scalar(
                    select(TaskActivityMatch).where(
                        TaskActivityMatch.task_id == task.id,
                        TaskActivityMatch.github_activity_id == activity.id,
                    )
                )
                if not existing_match:
                    session.add(TaskActivityMatch(
                        task_id=task.id,
                        github_activity_id=activity.id,
                        confidence=0.85,
                        reason=f"PR #{pr_number} references #{ref}",
                    ))
                task.last_activity_at = datetime.utcnow()
        await session.commit()


async def _find_task_by_ref(session, repo: GithubRepo | None, ref: str) -> Task | None:
    if not repo:
        return None
    # Try numeric ref as task priority match, or UUID prefix
    integration = await session.scalar(
        select(Integration).where(Integration.id == repo.integration_id)
    )
    if not integration:
        return None
    from ...models.work import Task
    # Search by title containing the ref, or external_refs
    tasks = (await session.scalars(
        select(Task).where(Task.workspace_id == integration.workspace_id)
    )).all()
    for task in tasks:
        if ref in task.title or ref in (task.description or ""):
            return task
        if task.external_refs and ref in str(task.external_refs):
            return task
    return None


async def _find_repo(session, payload: dict) -> GithubRepo | None:
    repo_info = payload.get("repository", {})
    full_name = repo_info.get("full_name")
    node_id = repo_info.get("node_id")
    if not full_name and not node_id:
        return None
    if node_id:
        repo = await session.scalar(
            select(GithubRepo).where(GithubRepo.github_node_id == node_id)
        )
        if repo:
            return repo
    if full_name:
        repo = await session.scalar(
            select(GithubRepo).where(GithubRepo.full_name == full_name)
        )
        if repo:
            return repo
    return None


@router.post("")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
) -> Response:
    body = await request.body()
    if not _verify(body, x_hub_signature_256 or ""):
        raise HTTPException(401, "Invalid GitHub webhook signature")
    payload = json.loads(body) if body else {}

    # Store raw event
    async with SessionLocal() as session:
        event = WebhookEvent(
            provider="github",
            event_id=x_github_delivery or "",
            event_type=x_github_event or "",
            payload=payload,
        )
        session.add(event)
        await session.commit()

    # Process the event
    try:
        async with SessionLocal() as session:
            repo = await _find_repo(session, payload)

        if x_github_event == "push":
            await _process_push_event(payload, repo)
        elif x_github_event == "pull_request":
            await _process_pr_event(payload, repo, payload.get("action", ""))
    except Exception:
        log.exception("GitHub webhook processing failed")

    return Response(content="{}", media_type="application/json")
