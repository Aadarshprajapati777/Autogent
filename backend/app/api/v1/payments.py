"""Payments endpoints. Create Razorpay orders and verify payments."""
import uuid
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.deps import current_user
from ...db.session import get_session
from ...models.core import User, WorkspaceMember
from ...models.payment import Payment, PaymentOrder
from ...services.payments import (
    PaymentError, create_order, is_configured, verify_payment_signature, fetch_payment,
)

router = APIRouter(prefix="/payments", tags=["payments"])


async def _check_member(workspace_id: uuid.UUID, user: User, session: AsyncSession) -> None:
    member = await session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not member:
        raise HTTPException(403, "Not a member of this workspace")


class CreateOrderRequest(BaseModel):
    workspace_id: uuid.UUID
    amount: int = Field(ge=1, description="Amount in paise (INR) or cents")
    currency: str = "INR"
    description: str | None = None


@router.get("/config")
async def payments_config() -> dict:
    return {"configured": is_configured(), "currency": "INR"}


@router.post("/orders")
async def create_payment_order(
    body: CreateOrderRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(body.workspace_id, user, session)
    if not is_configured():
        raise HTTPException(400, "Razorpay is not configured")
    try:
        order = create_order(
            amount=body.amount, currency=body.currency, description=body.description,
            customer_email=user.email, customer_name=user.display_name,
        )
    except PaymentError as exc:
        raise HTTPException(exc.status_code, str(exc))
    record = PaymentOrder(
        workspace_id=body.workspace_id,
        user_id=user.id,
        razorpay_order_id=order["id"],
        amount=body.amount,
        currency=body.currency,
        status=order.get("status", "created"),
        description=body.description,
        customer_email=user.email,
        customer_name=user.display_name,
    )
    session.add(record)
    await session.commit()
    return {
        "order_id": str(record.id),
        "razorpay_order_id": order["id"],
        "amount": body.amount,
        "currency": body.currency,
        "key_id": order.get("key_id") or "",
    }


class VerifyPaymentRequest(BaseModel):
    workspace_id: uuid.UUID
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/verify")
async def verify_payment(
    body: VerifyPaymentRequest,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(body.workspace_id, user, session)
    if not verify_payment_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        raise HTTPException(400, "Invalid payment signature")
    order = await session.scalar(
        select(PaymentOrder).where(
            PaymentOrder.workspace_id == body.workspace_id,
            PaymentOrder.razorpay_order_id == body.razorpay_order_id,
        )
    )
    if not order:
        raise HTTPException(404, "Order not found")
    payment_data = fetch_payment(body.razorpay_payment_id)
    payment = Payment(
        workspace_id=body.workspace_id,
        order_id=order.id,
        razorpay_payment_id=body.razorpay_payment_id,
        razorpay_order_id=body.razorpay_order_id,
        razorpay_signature=body.razorpay_signature,
        amount=order.amount,
        currency=order.currency,
        status="captured",
        method=payment_data.get("method"),
        raw_response=payment_data,
    )
    session.add(payment)
    order.status = "paid"
    await session.commit()
    return {"verified": True, "payment_id": str(payment.id), "status": "captured"}


@router.get("")
async def list_payments(
    workspace_id: uuid.UUID = Query(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    await _check_member(workspace_id, user, session)
    payments = (await session.execute(
        select(Payment).where(Payment.workspace_id == workspace_id)
    )).scalars().all()
    return {
        "count": len(payments),
        "payments": [
            {
                "id": str(p.id),
                "amount": p.amount,
                "currency": p.currency,
                "status": p.status,
                "method": p.method,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in payments
        ],
    }
