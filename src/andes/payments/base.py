"""Payment provider abstraction.

The booking flow only needs to authorize a charge and receive a status. Wompi
(the Colombian PSP) is the production target; a deterministic fake keeps the
system offline-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChargeResult:
    provider: str
    reference: str
    status: str
    amount: int
    currency: str = "COP"


class PaymentProvider(Protocol):
    def create_charge(self, reference: str, amount: int, currency: str = "COP") -> ChargeResult: ...


class FakePaymentProvider:
    """Deterministic provider for local runs and tests."""

    def create_charge(self, reference: str, amount: int, currency: str = "COP") -> ChargeResult:
        return ChargeResult(
            provider="fake",
            reference=reference,
            status="APPROVED",
            amount=amount,
            currency=currency,
        )
