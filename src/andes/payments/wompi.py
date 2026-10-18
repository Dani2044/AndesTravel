"""Wompi adapter (sandbox and production).

Two calls are all the integration needs:

- ``GET /merchants/info`` with the public key, which answers with the
  ``acceptance_token`` the customer's acceptance of the terms stands for.
- ``POST /transactions`` with the private key, signed with the integrity
  formula. A transaction is born ``PENDING``; it is never approved in this call.

The webhook settles it. Events carry their own ``signature.properties`` naming
which fields were signed; the checksum is verified before anything is trusted
about them.

Keys come from the environment and never from the code
(``WOMPI_MODE``, ``WOMPI_PUBLIC_KEY``, ``WOMPI_PRIVATE_KEY``,
``WOMPI_INTEGRITY_SECRET``, ``WOMPI_EVENTS_SECRET``). No card data, token or
contact detail is stored here: it goes to Wompi and stops existing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from andes.core.config import Settings, get_settings
from andes.payments.base import ChargeResult, FakePaymentProvider, PaymentProvider
from andes.payments.signatures import (
    DEFAULT_CURRENCY,
    event_signature,
    integrity_signature,
    verify_event,
)

SANDBOX_URL = "https://sandbox.wompi.co/v1"
PRODUCTION_URL = "https://production.wompi.co/v1"
TIMEOUT_SECONDS = 30.0

_WOMPI_STATUS = {
    "APPROVED": "APPROVED",
    "PENDING": "PENDING",
    "DECLINED": "DECLINED",
    "VOIDED": "DECLINED",
    "ERROR": "DECLINED",
}


@dataclass(frozen=True)
class PaymentEvent:
    event_id: str
    reference: str | None
    transaction_id: str | None
    status: str


def _translate_status(status: Any) -> str:
    return _WOMPI_STATUS.get(str(status or "").upper(), "PENDING")


def parse_event(event: dict[str, Any]) -> PaymentEvent:
    """Everything about an event that is worth persisting: who, what, and how much it moved."""
    data = event.get("data") or {}
    transaction = data.get("transaction") or {}
    return PaymentEvent(
        event_id=str(event.get("id") or transaction.get("id") or ""),
        reference=transaction.get("reference"),
        transaction_id=transaction.get("id"),
        status=_translate_status(transaction.get("status")),
    )


@dataclass
class WompiSandbox:
    """The real gateway. An httpx client can be injected for tests; otherwise one is
    opened per call, because a charge is a one-shot and not worth a pool."""

    public_key: str = ""
    private_key: str = ""
    events_secret: str = ""
    integrity_secret: str = ""
    base: str = SANDBOX_URL
    client: httpx.AsyncClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.public_key and self.private_key and self.integrity_secret)

    async def create_charge(
        self,
        reference: str,
        amount: int,
        currency: str = DEFAULT_CURRENCY,
        email: str = "",
        redirect_url: str | None = None,
    ) -> ChargeResult:
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
        try:
            token = await self._acceptance_token(client)
            body: dict[str, Any] = {
                "acceptance_token": token,
                "amount_in_cents": amount,
                "currency": currency,
                "customer_email": email,
                "reference": reference,
                "signature": integrity_signature(
                    reference, amount, currency, self.integrity_secret
                ),
            }
            if redirect_url:
                body["redirect_url"] = redirect_url
            response = await client.post(
                f"{self.base}/transactions",
                headers={"Authorization": f"Bearer {self.private_key}"},
                json=body,
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
            return ChargeResult(
                provider="wompi",
                reference=reference,
                status=_translate_status(data.get("status")),
                amount=amount,
                currency=currency,
                transaction_id=data.get("id"),
                redirect_url=data.get("redirect_url") or redirect_url,
            )
        finally:
            if owns_client:
                await client.aclose()

    async def _acceptance_token(self, client: httpx.AsyncClient) -> str:
        response = await client.get(
            f"{self.base}/merchants/info",
            headers={"x-merchant-public-key": self.public_key},
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        presigned = data.get("presigned_acceptance") or {}
        return presigned.get("acceptance_token", "")

    def verify(self, event: dict[str, Any]) -> bool:
        return verify_event(event, self.events_secret)


def payment_provider_from_settings(settings: Settings | None = None) -> PaymentProvider:
    """`WOMPI_MODE=sandbox` means the four keys are mandatory and a missing one is a startup
    error, not a silent downgrade to the fake: half-configured credentials that would charge
    real money are worse than an assistant that refuses to boot."""
    settings = settings or get_settings()
    if settings.wompi_mode != "sandbox":
        return FakePaymentProvider()
    keys = {
        "wompi_public_key": settings.wompi_public_key,
        "wompi_private_key": settings.wompi_private_key,
        "wompi_events_secret": settings.wompi_events_secret,
        "wompi_integrity_secret": settings.wompi_integrity_secret,
    }
    missing = [name for name, value in keys.items() if not value]
    if missing:
        raise RuntimeError("WOMPI_MODE=sandbox needs these keys set: " + ", ".join(missing))
    return WompiSandbox(
        public_key=settings.wompi_public_key or "",
        private_key=settings.wompi_private_key or "",
        events_secret=settings.wompi_events_secret or "",
        integrity_secret=settings.wompi_integrity_secret or "",
    )


__all__ = [
    "PaymentEvent",
    "WompiSandbox",
    "SANDBOX_URL",
    "PRODUCTION_URL",
    "event_signature",
    "integrity_signature",
    "parse_event",
    "payment_provider_from_settings",
    "verify_event",
]
