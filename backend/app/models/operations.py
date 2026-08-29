import enum, uuid
from datetime import datetime
from sqlalchemy import Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, Timestamped, UUIDPrimaryKey


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Reminder(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "reminders"
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scheduled_for: Mapped[datetime] = mapped_column(nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status"),
        default=DeliveryStatus.PENDING,
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    tone: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        Index("ix_reminders_pending_schedule", "status", "scheduled_for"),
        Index("ix_reminders_task_created", "task_id", "created_at"),
        UniqueConstraint("task_id", "body_hash"),
    )


class Escalation(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "escalations"
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    escalated_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    level: Mapped[int] = mapped_column(nullable=False, default=1)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (Index("ix_escalations_task_open", "task_id", "resolved_at"),)


class EscalationRule(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "escalation_rules"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    priority: Mapped[int] = mapped_column(nullable=False, default=100)
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    action: Mapped[dict] = mapped_column(JSONB, nullable=False)
    __table_args__ = (
        Index(
            "ix_escalation_rules_workspace_priority",
            "workspace_id",
            "enabled",
            "priority",
        ),
    )


class WeeklyReport(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "weekly_reports"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    __table_args__ = (
        Index(
            "ix_reports_workspace_period", "workspace_id", "period_start", unique=True
        ),
    )


class Insight(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "insights"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    weekly_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("weekly_reports.id", ondelete="SET NULL")
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        Index("ix_insights_workspace_key_created", "workspace_id", "key", "created_at"),
    )


class AuditLog(UUIDPrimaryKey, Base):
    __tablename__ = "audit_logs"
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(150), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    __table_args__ = (
        Index("ix_audit_org_created", "organization_id", "created_at"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )


class Notification(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "notifications"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "read_at", "created_at"),
    )
