import enum, uuid
from datetime import datetime
from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, Timestamped, UUIDPrimaryKey


class IntegrationProvider(str, enum.Enum):
    RECALL = "recall"
    GITHUB = "github"
    JIRA = "jira"
    LINEAR = "linear"
    GOOGLE_CALENDAR = "google_calendar"
    MICROSOFT_CALENDAR = "microsoft_calendar"
    SLACK = "slack"
    NOTION = "notion"


class IntegrationState(str, enum.Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class Integration(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "integrations"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        Enum(IntegrationProvider, name="integration_provider"), nullable=False
    )
    state: Mapped[IntegrationState] = mapped_column(
        Enum(IntegrationState, name="integration_state"),
        default=IntegrationState.CONNECTED,
        nullable=False,
    )
    external_account_id: Mapped[str | None] = mapped_column(String(200))
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", "external_account_id"),
        Index("ix_integrations_workspace_provider", "workspace_id", "provider"),
    )


class OAuthCredential(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "oauth_credentials"
    integration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    scopes: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    __table_args__ = (Index("ix_oauth_expiry", "expires_at"),)


class GithubRepo(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "github_repos"
    integration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    github_node_id: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(300), nullable=False)
    default_branch: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (
        UniqueConstraint("integration_id", "github_node_id"),
        Index("ix_repos_integration_active", "integration_id", "is_active"),
    )


class GithubActivity(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "github_activities"
    repo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("github_repos.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    __table_args__ = (
        UniqueConstraint("repo_id", "external_id"),
        Index("ix_github_activity_repo_occurred", "repo_id", "occurred_at"),
        Index("ix_github_activity_actor_occurred", "actor_id", "occurred_at"),
    )


class CalendarEvent(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "calendar_events"
    integration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    attendees: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    __table_args__ = (
        UniqueConstraint("integration_id", "external_id"),
        Index("ix_calendar_owner_starts", "owner_id", "starts_at"),
    )


class ExternalTaskMapping(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "external_task_mappings"
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    external_key: Mapped[str | None] = mapped_column(String(100))
    last_status: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    __table_args__ = (
        UniqueConstraint("integration_id", "external_id"),
        UniqueConstraint("task_id", "integration_id"),
        Index("ix_mappings_integration_sync", "integration_id", "last_synced_at"),
    )


class OAuthState(UUIDPrimaryKey, Base):
    __tablename__ = "oauth_states"
    provider: Mapped[IntegrationProvider] = mapped_column(
        Enum(IntegrationProvider, name="oauth_state_provider"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    __table_args__ = (Index("ix_oauth_state_expiry", "expires_at"),)
