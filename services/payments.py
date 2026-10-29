import logging
import secrets
from dataclasses import dataclass
from decimal import Decimal

import httpx

from exceptions import BadRequestError

from config import settings

logger = logging.getLogger("ticketflow.payments")

PAYSTACK_URL = "https://api.paystack.co"


@dataclass
class PaymentSession:
    reference: str
    authorization_url: str


def _new_reference(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(18)}"


def _kobo(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def _paystack(method: str, path: str, **kwargs) -> dict:
    try:
        resp = httpx.request(
            method,
            f"{PAYSTACK_URL}{path}",
            headers={"Authorization": f"Bearer {settings.paystack_secret_key}"},
            timeout=15,
            **kwargs,
        )
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.exception("Paystack request failed: %s %s", method, path)
        raise BadRequestError(
            "Payment provider is unavailable, try again shortly"
        ) from exc
    if resp.status_code >= 400 or not data.get("status"):
        logger.warning("Paystack error on %s: %s", path, data)
        raise BadRequestError(
            data.get("message") or "Payment provider rejected the request"
        )
    return data["data"]


def initialize(email: str, amount: Decimal) -> PaymentSession:
    """Start a payment for `amount` (major units, e.g. naira)."""
    if amount <= 0:
        return PaymentSession(reference=_new_reference("free"), authorization_url="")
    reference = _new_reference("tf")
    if settings.payment_provider == "paystack":
        data = _paystack(
            "POST",
            "/transaction/initialize",
            json={
                "email": email,
                "amount": _kobo(amount),
                "reference": reference,
                "currency": settings.currency,
            },
        )
        return PaymentSession(
            reference=data["reference"], authorization_url=data["authorization_url"]
        )
    return PaymentSession(
        reference=reference,
        authorization_url=f"https://mock-pay.local/checkout/{reference}",
    )


def verify(reference: str, amount: Decimal) -> bool:
    """True only if the provider says this reference was paid in full."""
    if amount <= 0:
        return reference.startswith("free_")
    if settings.payment_provider == "paystack":
        data = _paystack("GET", f"/transaction/verify/{reference}")
        return (
            data.get("status") == "success"
            and int(data.get("amount", 0)) >= _kobo(amount)
            and data.get("currency", settings.currency) == settings.currency
        )
    return reference.startswith("tf_")  # mock: any issued reference counts as paid


def refund(reference: str) -> None:
    if settings.payment_provider == "paystack" and not reference.startswith("free_"):
        _paystack("POST", "/refund", json={"transaction": reference})
