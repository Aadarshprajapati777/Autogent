"""In-backend memory store. Replaces the separate kgmemory microservice.

The agent's long-term memory lives in the same Postgres DB as the rest of
Autogent. Facts are (subject, predicate, value) triples with kind, topics,
temporal status and confidence — the same shape kgmemory used, but persisted
as rows instead of graph nodes. People and projects are first-class tables
so the agent can build rich profiles and project health views via tools.
"""
import enum, uuid
from datetime import datetime
from sqlalchemy import Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, Timestamped, UUIDPrimaryKey


class FactKind(str, enum.Enum):
    FACT = "fact"
    SKILL = "skill"
    STATUS_UPDATE = "status_update"
    COMMITMENT = "commitment"
    BLOCKER = "blocker"
    DECISION = "decision"
    REQUIREMENT = "requirement"
    IDEA = "idea"
    RISK = "risk"
    PERFORMANCE = "performance"
    AVAILABILITY = "availability"
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    IDENTITY = "identity"


class TemporalStatus(str, enum.Enum):
    CURRENT = "current"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class SpeakerRole(str, enum.Enum):
    FOUNDER = "founder"
    ENGINEER = "engineer"
    MARKETER = "marketer"
    MANAGER = "manager"
    ASSISTANT = "assistant"
    OTHER = "other"


class PersonRole(str, enum.Enum):
    FOUNDER = "founder"
    ENGINEER = "engineer"
    MARKETER = "marketer"
    MANAGER = "manager"
    DESIGNER = "designer"
    OTHER = "other"


class ProjectStatus(str, enum.Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MemoryTaskStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class Fact(UUIDPrimaryKey, Timestamped, Base):
    """A (subject, predicate, value) triple extracted from any conversation.
    The agent's atomic unit of memory. fact_id is a deterministic uuid5 so
    re-ingesting the same fact supersedes instead of duplicating.
    """
    __tablename__ = "memory_facts"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    predicate: Mapped[str] = mapped_column(String(150), nullable=False)
    value: Mapped[str] = mapped_column(String(2000), nullable=False)
    fact_kind: Mapped[FactKind] = mapped_column(
        Enum(FactKind, name="memory_fact_kind"), default=FactKind.FACT, nullable=False
    )
    topics: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    entities: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    project: Mapped[str | None] = mapped_column(String(200), index=True)
    task: Mapped[str | None] = mapped_column(String(200))
    numeric_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(64))
    sentiment: Mapped[str] = mapped_column(String(32), default="neutral", nullable=False)
    temporal_hint: Mapped[str] = mapped_column(
        String(32), default="current", nullable=False
    )
    due_date: Mapped[str | None] = mapped_column(String(32))
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    speaker: Mapped[str | None] = mapped_column(String(200))
    speaker_role: Mapped[SpeakerRole] = mapped_column(
        Enum(SpeakerRole, name="memory_speaker_role"),
        default=SpeakerRole.OTHER,
        nullable=False,
    )
    episode_id: Mapped[str | None] = mapped_column(String(128), index=True)
    temporal_status: Mapped[TemporalStatus] = mapped_column(
        Enum(TemporalStatus, name="memory_temporal_status"),
        default=TemporalStatus.CURRENT,
        nullable=False,
    )
    valid_from: Mapped[datetime] = mapped_column(nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    __table_args__ = (
        UniqueConstraint("workspace_id", "fact_id"),
        Index("ix_memory_facts_subject", "workspace_id", "subject"),
        Index("ix_memory_facts_project_kind", "workspace_id", "project", "fact_kind"),
    )


class Person(UUIDPrimaryKey, Timestamped, Base):
    """A person the agent knows about. Built up automatically from facts and
    integrations (Slack profile, GitHub user, meeting participant). The agent
    uses this for profile creation and reliability scoring.
    """
    __tablename__ = "memory_people"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[PersonRole] = mapped_column(
        Enum(PersonRole, name="memory_person_role"),
        default=PersonRole.OTHER,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(200))
    skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    languages: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    is_technical: Mapped[bool] = mapped_column(default=False, nullable=False)
    experience_years: Mapped[float | None] = mapped_column(Float)
    availability_hours_per_week: Mapped[float | None] = mapped_column(Float)
    timezone: Mapped[str | None] = mapped_column(String(100))
    interests: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    career_goals: Mapped[str | None] = mapped_column(Text)
    resume_summary: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    __table_args__ = (
        UniqueConstraint("workspace_id", "name"),
        Index("ix_memory_people_role", "workspace_id", "role"),
    )


class Project(UUIDPrimaryKey, Timestamped, Base):
    """A project the agent tracks. Health is derived from its tasks and facts.
    """
    __tablename__ = "memory_projects"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="memory_project_status"),
        default=ProjectStatus.PLANNING,
        nullable=False,
    )
    deadline: Mapped[str | None] = mapped_column(String(32))
    __table_args__ = (
        UniqueConstraint("workspace_id", "name"),
        Index("ix_memory_projects_status", "workspace_id", "status"),
    )


class MemoryTask(UUIDPrimaryKey, Timestamped, Base):
    """A lightweight task tracked inside memory (commitments, blockers).
    Distinct from the work.Task table which is the canonical execution tracker;
    memory tasks are what the agent extracts and can promote to work tasks.
    """
    __tablename__ = "memory_tasks"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_projects.id", ondelete="SET NULL")
    )
    assignee_person_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_people.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[MemoryTaskStatus] = mapped_column(
        Enum(MemoryTaskStatus, name="memory_task_status"),
        default=MemoryTaskStatus.OPEN,
        nullable=False,
    )
    required_skills: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    estimated_days: Mapped[float | None] = mapped_column(Float)
    deadline: Mapped[str | None] = mapped_column(String(32))
    source_fact_id: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        Index("ix_memory_tasks_status", "workspace_id", "status"),
        Index("ix_memory_tasks_project", "workspace_id", "project_id"),
    )


class IngestEpisode(UUIDPrimaryKey, Timestamped, Base):
    """One ingested conversation message (Slack, meeting, chat). Facts link
    back here via Fact.episode_id so we keep provenance.
    """
    __tablename__ = "memory_episodes"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    episode_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    speaker: Mapped[str] = mapped_column(String(200), nullable=False)
    speaker_role: Mapped[SpeakerRole] = mapped_column(
        Enum(SpeakerRole, name="memory_episode_speaker_role"),
        default=SpeakerRole.OTHER,
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(64), default="api", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    project: Mapped[str | None] = mapped_column(String(200))
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    fact_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    __table_args__ = (
        UniqueConstraint("workspace_id", "episode_id"),
    )
