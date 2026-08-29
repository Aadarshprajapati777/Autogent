import uuid
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from ..db.base import Base, Timestamped, UUIDPrimaryKey


class PaymentOrder(UUIDPrimaryKey, Timestamped, Base):
    """A Razorpay order created by the backend. An order is an intent to
    collect payment; once the user pays on checkout a Payment is created
    and linked via razorpay_order_id.
    """
    __tablename__ = "payment_orders"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    razorpay_order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # paise (INR) / cents
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="created")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_contact: Mapped[str | None] = mapped_column(String(20), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    __table_args__ = (
        Index("ix_payment_orders_workspace", "workspace_id"),
        Index("ix_payment_orders_razorpay_order", "razorpay_order_id"),
    )


class Payment(UUIDPrimaryKey, Timestamped, Base):
    """A completed (or failed) payment linked to a Razorpay order. Created
    after checkout completes via webhook or manual verification.
    """
    __tablename__ = "payments"
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payment_orders.id", ondelete="CASCADE"), nullable=False
    )
    razorpay_payment_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    razorpay_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    razorpay_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="captured")
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    __table_args__ = (
        Index("ix_payments_workspace", "workspace_id"),
        Index("ix_payments_razorpay_payment", "razorpay_payment_id"),
    )
