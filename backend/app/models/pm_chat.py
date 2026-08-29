import uuid
from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, Timestamped, UUIDPrimaryKey


class PmChatMessage(UUIDPrimaryKey, Timestamped, Base):
    """A single message in a user's conversation with the agent. History is
    scoped per workspace + user so each dashboard user keeps their own
    persistent thread. `actions` stores the agent's tool calls and their
    results so the conversation can be restored exactly.
    """
    __tablename__ = "pm_chat_messages"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    actions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    __table_args__ = (
        Index(
            "ix_pm_chat_workspace_user_created",
            "workspace_id",
            "user_id",
            "created_at",
        ),
    )
