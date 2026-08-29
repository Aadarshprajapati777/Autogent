import enum, uuid
from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db.base import Base, Timestamped, UUIDPrimaryKey


class MemberRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Organization(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True, index=True
    )
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    workspaces: Mapped[list["Workspace"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class Workspace(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "workspaces"
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    organization: Mapped["Organization"] = relationship(back_populates="workspaces")
    members: Mapped[list["WorkspaceMember"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    __table_args__ = (
        UniqueConstraint("organization_id", "slug"),
        Index("ix_workspaces_org_created", "organization_id", "created_at"),
    )


class User(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "users"
    clerk_id: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(160))
    skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    notification_preferences: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_login_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class ExternalIdentity(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "external_identities"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(200), nullable=False)
    __table_args__ = (
        UniqueConstraint("provider", "external_user_id"),
        Index("ix_external_identity_user", "user_id"),
    )


class WorkspaceMember(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "workspace_members"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MemberRole] = mapped_column(
        Enum(MemberRole, name="member_role"), default=MemberRole.MEMBER, nullable=False
    )
    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship()
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id"),
        Index("ix_members_user_workspace", "user_id", "workspace_id"),
    )
