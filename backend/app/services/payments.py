"""Razorpay payment service. Wraps the Razorpay SDK for order creation,
signature verification, and webhook handling.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

try:
    import pkg_resources  # noqa: F401
except ImportError:
    import sys, types
    if "pkg_resources" not in sys.modules:
        stub = types.ModuleType("pkg_resources")
        _Dist = type("Dist", (), {"version": "0.0.0", "project_name": "razorpay"})
        stub.get_distribution = lambda name: _Dist()
        stub.require = lambda *a, **kw: []
        stub.DistributionNotFound = type("DistributionNotFound", (Exception,), {})
        stub.parse_version = lambda v: tuple(int(x) for x in str(v).split(".") if x.isdigit())
        sys.modules["pkg_resources"] = stub

import razorpay

from ..config import settings

logger = logging.getLogger(__name__)
_client: razorpay.Client | None = None


def get_client() -> razorpay.Client | None:
    global _client
    if _client is not None:
        return _client
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        return None
    _client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
    return _client


def is_configured() -> bool:
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


class PaymentError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.status_code = status_code
        super().__init__(message)


def create_order(
    amount: int, currency: str = "INR", description: str | None = None,
    customer_name: str | None = None, customer_email: str | None = None,
    customer_contact: str | None = None, notes: dict[str, str] | None = None,
) -> dict[str, Any]:
    client = get_client()
    if client is None:
        raise PaymentError("Razorpay is not configured. Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")
    try:
        order_data: dict[str, Any] = {"amount": amount, "currency": currency, "payment_capture": 1}
        if description:
            order_data["notes"] = {"description": description}
        if notes:
            order_data["notes"] = {**(order_data.get("notes") or {}), **notes}
        return client.order.create(order_data)
    except razorpay.errors.ServerError as exc:
        raise PaymentError(f"Razorpay server error: {exc}", 502)
    except razorpay.errors.BadRequestError as exc:
        raise PaymentError(f"Invalid request: {exc}", 400)
    except Exception as exc:
        raise PaymentError(f"Failed to create order: {exc}", 500)


def verify_payment_signature(
    razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str,
) -> bool:
    client = get_client()
    if client is None:
        raise PaymentError("Razorpay is not configured.")
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })
        return True
    except razorpay.errors.SignatureVerificationError:
        return False
    except Exception:
        return False


def fetch_payment(razorpay_payment_id: str) -> dict[str, Any]:
    client = get_client()
    if client is None:
        raise PaymentError("Razorpay is not configured.")
    return client.payment.fetch(razorpay_payment_id)


def verify_webhook_signature(webhook_body: bytes, webhook_signature: str) -> bool:
    if not settings.razorpay_webhook_secret:
        return False
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(), webhook_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, webhook_signature)
