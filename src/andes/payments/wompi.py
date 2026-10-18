"""Wompi sandbox integration.

``TODO(human)``: set ``WOMPI_*`` credentials and point the Wompi event webhook at
``POST /webhooks/wompi``. Until then charges fall back to the deterministic fake.

Wompi integrity signature: ``SHA256(reference + amount_in_cents + currency +
integrity_secret)``. Event checksums are verified the same way over the values of
the properties listed in ``signature.properties`` plus the events secret.
"""

from __future__ import annotations

import hashlib

from andes.core.config import get_settings
from andes.payments.base import ChargeResult, FakePaymentProvider


def integrity_signature(reference: str, amount_in_cents: int, currency: str, secret: str) -> str:
    payload = f"{reference}{amount_in_cents}{currency}{secret}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_event(event: dict, secret: str) -> bool:
    signature = event.get("signature", {})
    properties = signature.get("properties", [])
    checksum = signature.get("checksum", "")
    concatenated = ""
    for path in properties:
        value = event
        for part in path.split("."):
            value = value.get(part, "") if isinstance(value, dict) else ""
        concatenated += str(value)
    expected = hashlib.sha256(f"{concatenated}{secret}".encode()).hexdigest()
    return expected == checksum


class WompiSandbox:
    """Wompi payment provider with a fake fallback when not configured."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._fake = FakePaymentProvider()

    @property
    def enabled(self) -> bool:
        return bool(self._settings.wompi_public_key and self._settings.wompi_private_key)

    def create_charge(self, reference: str, amount: int, currency: str = "COP") -> ChargeResult:
        if not self.enabled:
            return self._fake.create_charge(reference, amount, currency)
        # TODO(human): POST to https://sandbox.wompi.co/v1/transactions and map
        # the response status here.
        return ChargeResult(
            provider="wompi",
            reference=reference,
            status="PENDING",
            amount=amount,
            currency=currency,
        )
