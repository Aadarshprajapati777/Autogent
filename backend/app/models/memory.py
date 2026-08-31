"""In-backend memory store. Replaces the separate kgmemory microservice.

The agent's long-term memory lives in the same Postgres DB as the rest of
Autogent. Facts are (subject, predicate, value) triples with kind, topics,
temporal status and confidence — the same shape kgmemory used, but persisted
as rows instead of graph nodes. People and projects are first-class tables
so the agent can build rich profiles and project health views via tools.
"""
import enum, uuid
from datetime import datetime
from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector
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
    # pgvector column for semantic search. 384-dim from BAAI/bge-small-en-v1.5.
    # Nullable so existing rows don't break; backfilled as facts are re-stored.
    embedding: Mapped[list | None] = mapped_column(Vector(384), nullable=True)
    __table_args__ = (
        # fact_id is deterministic, but we keep multiple versions (current +
        # superseded) so the unique constraint is on (workspace_id, fact_id,
        # temporal_status) instead of just (workspace_id, fact_id).
        UniqueConstraint("workspace_id", "fact_id", "temporal_status"),
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
    # Integration-linked fields — a single Person can be matched across
    # Slack, GitHub, Jira, and meetings via email (primary) or name.
    email: Mapped[str | None] = mapped_column(String(300), index=True)
    slack_id: Mapped[str | None] = mapped_column(String(50), index=True)
    slack_handle: Mapped[str | None] = mapped_column(String(100))
    github_login: Mapped[str | None] = mapped_column(String(100))
    github_id: Mapped[str | None] = mapped_column(String(50))
    jira_account_id: Mapped[str | None] = mapped_column(String(100))
    jira_display_name: Mapped[str | None] = mapped_column(String(200))
    linear_id: Mapped[str | None] = mapped_column(String(50))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    onboarding_step: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
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


class FactRelation(UUIDPrimaryKey, Timestamped, Base):
    """A directed edge between two facts: causes, influences, blocks, depends_on.
    Replaces the graph edges kgmemory used — stored as a simple join table.
    """
    __tablename__ = "memory_fact_relations"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_fact_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    to_fact_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    __table_args__ = (
        UniqueConstraint("workspace_id", "from_fact_id", "to_fact_id", "relation_type"),
    )


class StateSnapshot(UUIDPrimaryKey, Timestamped, Base):
    """A point-in-time inference of project health or person credibility.
    The state inference service writes these after each ingest cycle so the
    PM always has a current view of reality without re-deriving from scratch.
    """
    __tablename__ = "memory_state_snapshots"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_signals: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    open_commitments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_since_last: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missed_or_late: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    days_since_last_seen: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        Index("ix_state_snapshots_entity", "workspace_id", "entity_type", "entity_name"),
    )


class CheckInRecord(UUIDPrimaryKey, Timestamped, Base):
    """Records each check-in message the PM sends so it doesn't repeat the
    same question. Expires after 14 days so old check-ins don't clutter.
    """
    __tablename__ = "memory_checkin_records"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    person_name: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    thread_ts: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        Index("ix_checkin_person", "workspace_id", "person_name"),
    )


class Alert(UUIDPrimaryKey, Timestamped, Base):
    """Autonomous risk alert — overdue commitments, engineer silence,
    single-point-of-failure, stale blockers. Deduped by signature."""
    __tablename__ = "memory_alerts"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    project: Mapped[str | None] = mapped_column(String(200), index=True)
    person: Mapped[str | None] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_fact_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (
        Index("ix_alerts_status", "workspace_id", "status"),
        Index("ix_alerts_type", "workspace_id", "alert_type"),
    )


class Sprint(UUIDPrimaryKey, Timestamped, Base):
    """A timeboxed sprint for a project."""
    __tablename__ = "memory_sprints"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sprint_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    project: Mapped[str] = mapped_column(String(200), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[datetime] = mapped_column(nullable=False)
    end_date: Mapped[datetime] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="planning", nullable=False)
    task_ids: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    __table_args__ = (
        Index("ix_sprints_project", "workspace_id", "project"),
    )


class Milestone(UUIDPrimaryKey, Timestamped, Base):
    """A project milestone with a target date."""
    __tablename__ = "memory_milestones"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    milestone_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    project: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    target_date: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="upcoming", nullable=False)
    __table_args__ = (
        Index("ix_milestones_project", "workspace_id", "project"),
    )


class Spend(UUIDPrimaryKey, Timestamped, Base):
    """A spend record against a project budget."""
    __tablename__ = "memory_spends"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    spend_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    project: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="general", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("ix_spends_project", "workspace_id", "project"),
    )


class DecisionHistory(UUIDPrimaryKey, Timestamped, Base):
    """Every PM decision stored durably so the system can learn from past
    outcomes and reference them in future reasoning."""
    __tablename__ = "memory_decision_history"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(String(40), default="founder_non_technical", nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk_level: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    suggested_actions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(20))
    outcome_notes: Mapped[str | None] = mapped_column(Text)
    outcome_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (
        Index("ix_decisions_workspace", "workspace_id", "created_at"),
    )


class ActionQueue(UUIDPrimaryKey, Timestamped, Base):
    """Durable queue for PM-suggested actions. The backend fetches and
    executes them (Slack pings, escalations) and marks them complete."""
    __tablename__ = "memory_action_queue"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    urgency: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (
        Index("ix_actions_status", "workspace_id", "status"),
    )
