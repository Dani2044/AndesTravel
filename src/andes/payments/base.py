"""Payment provider port.

A booking only needs to send money to be collected and to learn the outcome
afterwards. Wompi (the Colombian PSP) is the production target; a deterministic
fake covers local runs and the test suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from andes.payments.signatures import event_signature


@dataclass(frozen=True)
class ChargeResult:
    provider: str
    reference: str
    status: str
    amount: int
    currency: str = "COP"
    transaction_id: str | None = None
    redirect_url: str | None = None


class PaymentProvider(Protocol):
    async def create_charge(
        self,
        reference: str,
        amount: int,
        currency: str = "COP",
        email: str = "",
        redirect_url: str | None = None,
    ) -> ChargeResult: ...


class FakePaymentProvider:
    """Deterministic provider: always approves and never touches the network."""

    events_secret = "test_events_secret"

    async def create_charge(
        self,
        reference: str,
        amount: int,
        currency: str = "COP",
        email: str = "",
        redirect_url: str | None = None,
    ) -> ChargeResult:
        return ChargeResult(
            provider="fake",
            reference=reference,
            status="APPROVED",
            amount=amount,
            currency=currency,
            transaction_id=f"fake-{reference}",
        )

    def signed_event(
        self,
        *,
        reference: str,
        transaction_id: str,
        status: str,
        timestamp: int = 1_700_000_000,
    ) -> dict:
        """A webhook signed the same way Wompi signs one, so verification is exercised for real."""
        event: dict = {
            "id": f"evt-{transaction_id}",
            "event": "transaction.updated",
            "timestamp": timestamp,
            "data": {
                "transaction": {
                    "id": transaction_id,
                    "reference": reference,
                    "status": status,
                }
            },
            "signature": {"properties": ["transaction.id", "transaction.status"], "checksum": ""},
        }
        event["signature"]["checksum"] = event_signature(event, self.events_secret)
        return event
