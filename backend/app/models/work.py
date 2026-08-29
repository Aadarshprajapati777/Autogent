import enum, uuid
from datetime import datetime
from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db.base import Base, Timestamped, UUIDPrimaryKey


class TaskState(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


class CandidateState(str, enum.Enum):
    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    MATERIALIZED = "materialized"


class Decision(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "decisions"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meetings.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.5)
    source_chunk_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    __table_args__ = (
        Index("ix_decisions_workspace_created", "workspace_id", "created_at"),
    )


class Task(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "tasks"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL")
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    state: Mapped[TaskState] = mapped_column(
        Enum(TaskState, name="task_state"), default=TaskState.OPEN, nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    execution_score: Mapped[float] = mapped_column(default=50, nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    external_refs: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(nullable=True)
    comments: Mapped[list["TaskComment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    __table_args__ = (
        Index("ix_tasks_workspace_state_due", "workspace_id", "state", "due_at"),
        Index("ix_tasks_owner_state_due", "owner_id", "state", "due_at"),
    )


class TaskCandidate(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "task_candidates"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting_extractions.id", ondelete="CASCADE")
    )
    ref: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    owner_name: Mapped[str | None] = mapped_column(String(200))
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    dependency_refs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    state: Mapped[CandidateState] = mapped_column(
        Enum(CandidateState, name="candidate_state"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL")
    )
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (
        UniqueConstraint("workspace_id", "extraction_id", "ref"),
        Index("ix_candidates_workspace_state", "workspace_id", "state", "created_at"),
    )


class TaskDependency(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "task_dependencies"
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    __table_args__ = (UniqueConstraint("task_id", "depends_on_task_id"),)


class TaskComment(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "task_comments"
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    task: Mapped["Task"] = relationship(back_populates="comments")
    __table_args__ = (Index("ix_comments_task_created", "task_id", "created_at"),)


class TaskStatusHistory(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "task_status_history"
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    from_state: Mapped[TaskState | None] = mapped_column(
        Enum(TaskState, name="task_state_history"), nullable=True
    )
    to_state: Mapped[TaskState] = mapped_column(
        Enum(TaskState, name="task_state_history_new"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_task_history_task_created", "task_id", "created_at"),)


class TaskActivityMatch(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "task_activity_matches"
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    github_activity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("github_activities.id", ondelete="CASCADE"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("task_id", "github_activity_id"),
        Index("ix_matches_task_confidence", "task_id", "confidence"),
    )
