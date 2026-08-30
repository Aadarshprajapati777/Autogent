import re
import uuid
import datetime
import jwt
import bcrypt
from pydantic import BaseModel, EmailStr, Field
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user, verified_claims
from ...config import settings
from ...db.session import get_session
from ...models.core import MemberRole, Organization, User, Workspace, WorkspaceMember

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# In-process rate limit counters (per IP). For multi-instance deployments,
# replace with Redis-backed limiter.
_auth_attempts: dict[str, list[float]] = {}
_RATE_WINDOW_SEC = 60.0
_RATE_MAX_AUTH = 10  # login/signup/forgot per minute per IP


def _check_auth_rate_limit(request: Request) -> None:
    import time
    ip = _client_ip(request)
    now = time.time()
    recent = [t for t in _auth_attempts.get(ip, []) if now - t < _RATE_WINDOW_SEC]
    if len(recent) >= _RATE_MAX_AUTH:
        raise HTTPException(429, "Too many auth attempts. Try again later.")
    recent.append(now)
    _auth_attempts[ip] = recent


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _create_jwt(user_id: uuid.UUID) -> str:
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + datetime.timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


class SignupRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


class BootstrapRequest(BaseModel):
    display_name: str
    email: EmailStr


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None
    timezone: str | None = None
    notification_preferences: dict | None = None


async def _bootstrap_workspace(session: AsyncSession, user: User) -> Workspace:
    stem = re.sub(r"[^a-z0-9]+", "-", user.display_name.lower()).strip("-") or "workspace"
    slug = f"{stem}-{str(user.id)[:8]}"
    org = Organization(name=f"{user.display_name}'s organization", slug=slug)
    session.add(org)
    await session.flush()
    ws = Workspace(organization_id=org.id, name="Main workspace", slug="main")
    session.add(ws)
    await session.flush()
    session.add(
        WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=MemberRole.OWNER)
    )
    await session.flush()
    return ws


async def _user_with_workspaces(session: AsyncSession, user: User) -> dict:
    """Build the user response dict including their workspaces."""
    rows = (
        await session.execute(
            select(Workspace, WorkspaceMember)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
        )
    ).all()
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.display_name,
        "workspaces": [
            {
                "id": str(workspace.id),
                "name": workspace.name,
                "slug": workspace.slug,
                "role": member.role.value,
            }
            for workspace, member in rows
        ],
    }


@router.post("/signup")
async def signup(
    body: SignupRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    _check_auth_rate_limit(request)
    existing = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "An account with this email already exists")

    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=_hash_password(body.password),
        is_login_enabled=True,
    )
    session.add(user)
    await session.flush()
    await _bootstrap_workspace(session, user)
    await session.commit()

    token = _create_jwt(user.id)
    return {"token": token, "user": await _user_with_workspaces(session, user)}


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    _check_auth_rate_limit(request)
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if not user or not user.password_hash:
        raise HTTPException(401, "Invalid email or password")
    if not _verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if not user.is_login_enabled or not user.is_active:
        raise HTTPException(403, "Account is disabled")
    token = _create_jwt(user.id)
    return {"token": token, "user": await _user_with_workspaces(session, user)}


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    _check_auth_rate_limit(request)
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if not user or not user.password_hash:
        return {"sent": True}
    now = datetime.datetime.now(datetime.UTC)
    reset_token = jwt.encode(
        {
            "sub": str(user.id),
            "purpose": "password_reset",
            "iat": now,
            "exp": now + datetime.timedelta(hours=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    reset_link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={reset_token}"
    if settings.smtp_host:
        from ...services.email import send_password_reset_email
        try:
            send_password_reset_email(user.email, user.display_name, reset_link)
        except Exception:
            import logging
            logging.exception("Failed to send password reset email")
            raise HTTPException(500, "Failed to send reset email. Please try again.")
        return {"sent": True}
    # In dev without SMTP, log the reset link. Never return the token in
    # the API response — that's an account-takeover vector.
    if not settings.is_production:
        import logging
        logging.getLogger(__name__).info(
            "Password reset requested for %s (no SMTP configured). "
            "Reset link: %s", user.email, reset_link,
        )
    return {"sent": True}


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        payload = jwt.decode(
            body.token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(400, "Reset link has expired. Please request a new one.")
    except jwt.PyJWTError:
        raise HTTPException(400, "Invalid reset token")
    if payload.get("purpose") != "password_reset":
        raise HTTPException(400, "Invalid reset token")
    user = (
        await session.execute(select(User).where(User.id == payload["sub"]))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if not user.is_active:
        raise HTTPException(403, "Account is disabled")
    user.password_hash = _hash_password(body.password)
    await session.commit()
    return {"reset": True}


@router.get("/me")
async def me(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    rows = (
        await session.execute(
            select(Workspace, WorkspaceMember)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
        )
    ).all()
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.display_name,
        "workspaces": [
            {
                "id": str(workspace.id),
                "name": workspace.name,
                "slug": workspace.slug,
                "role": member.role.value,
            }
            for workspace, member in rows
        ],
    }


@router.post("/bootstrap")
async def bootstrap(
    body: BootstrapRequest,
    claims: dict = Depends(verified_claims),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Clerk-based bootstrap: create the user + workspace on first dashboard
    visit using the Clerk session claims."""
    user = (
        await session.execute(select(User).where(User.clerk_id == claims["sub"]))
    ).scalar_one_or_none()
    if not user:
        user = User(
            clerk_id=claims["sub"],
            email=body.email,
            display_name=body.display_name,
            is_login_enabled=True,
        )
        session.add(user)
        await session.commit()
    if user.email != body.email:
        raise HTTPException(400, "Authenticated identity email mismatch")
    membership = (
        await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not membership:
        await _bootstrap_workspace(session, user)
        await session.commit()
    return {"user_id": str(user.id), "onboarding_required": False}


@router.patch("/profile")
async def update_profile(
    body: ProfileUpdate,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    await session.commit()
    return {
        "id": str(user.id),
        "display_name": user.display_name,
        "timezone": user.timezone,
        "notification_preferences": user.notification_preferences,
    }


@router.post("/logout")
async def logout() -> dict:
    return {"revoked": True}
