import enum, uuid
from datetime import datetime
from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..db.base import Base, Timestamped, UUIDPrimaryKey


class MeetingProvider(str, enum.Enum):
    GOOGLE_MEET = "google_meet"
    ZOOM = "zoom"
    MICROSOFT_TEAMS = "microsoft_teams"
    SLACK_HUDDLE = "slack_huddle"


class MeetingStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    JOINING = "joining"
    IN_PROGRESS = "in_progress"
    ENDED = "ended"
    FAILED = "failed"


class Meeting(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "meetings"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[MeetingProvider] = mapped_column(
        Enum(MeetingProvider, name="meeting_provider"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(200))
    recall_bot_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    join_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[MeetingStatus] = mapped_column(
        Enum(MeetingStatus, name="meeting_status"),
        default=MeetingStatus.SCHEDULED,
        nullable=False,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", uselist=False
    )
    __table_args__ = (
        Index(
            "ix_meetings_workspace_status_scheduled",
            "workspace_id",
            "status",
            "scheduled_at",
        ),
        Index("ix_meetings_provider_external", "provider", "external_id"),
    )


class MeetingParticipant(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "meeting_participants"
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    external_participant_id: Mapped[str | None] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(300), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    joined_at: Mapped[datetime | None] = mapped_column(nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(nullable=True)
    meeting: Mapped["Meeting"] = relationship(back_populates="participants")
    __table_args__ = (
        UniqueConstraint("meeting_id", "external_participant_id"),
        Index("ix_participants_meeting_user", "meeting_id", "user_id"),
    )


class Transcript(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "transcripts"
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    recall_transcript_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="capturing", nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    meeting: Mapped["Meeting"] = relationship(back_populates="transcript")
    chunks: Mapped[list["TranscriptChunk"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan"
    )
    extraction: Mapped["MeetingExtraction | None"] = relationship(
        back_populates="transcript", cascade="all, delete-orphan", uselist=False
    )


class MeetingExtraction(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "meeting_extractions"
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    result: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped["Transcript"] = relationship(back_populates="extraction")
    __table_args__ = (Index("ix_extractions_status_created", "status", "created_at"),)


class Speaker(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "speakers"
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    participant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting_participants.id", ondelete="SET NULL")
    )
    provider_speaker_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(300))
    __table_args__ = (UniqueConstraint("meeting_id", "provider_speaker_id"),)


class TranscriptChunk(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "transcript_chunks"
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("speakers.id", ondelete="SET NULL")
    )
    provider_utterance_id: Mapped[str] = mapped_column(String(200), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    started_ms: Mapped[int | None] = mapped_column(Integer)
    ended_ms: Mapped[int | None] = mapped_column(Integer)
    is_final: Mapped[bool] = mapped_column(default=True, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    transcript: Mapped["Transcript"] = relationship(back_populates="chunks")
    __table_args__ = (
        UniqueConstraint("transcript_id", "provider_utterance_id"),
        Index("ix_chunks_transcript_sequence", "transcript_id", "sequence"),
    )
