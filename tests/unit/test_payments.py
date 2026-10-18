from __future__ import annotations

import hashlib

from andes.payments.base import FakePaymentProvider
from andes.payments.wompi import WompiSandbox, integrity_signature, verify_event


def test_fake_provider_approves():
    result = FakePaymentProvider().create_charge("ref-1", 5_000_000)
    assert result.status == "APPROVED"
    assert result.amount == 5_000_000


def test_integrity_signature_is_deterministic():
    first = integrity_signature("ref-1", 5_000_000, "COP", "secret")
    second = integrity_signature("ref-1", 5_000_000, "COP", "secret")
    assert first == second
    assert first != integrity_signature("ref-2", 5_000_000, "COP", "secret")


def _signed_event(secret: str) -> dict:
    event = {
        "event": "transaction.updated",
        "data": {"transaction": {"reference": "ref-1", "status": "APPROVED"}},
        "signature": {
            "properties": ["data.transaction.reference", "data.transaction.status"],
            "checksum": "",
        },
    }
    concatenated = "ref-1APPROVED"
    event["signature"]["checksum"] = hashlib.sha256(f"{concatenated}{secret}".encode()).hexdigest()
    return event


def test_verify_event_accepts_valid_checksum():
    assert verify_event(_signed_event("events-secret"), "events-secret") is True


def test_verify_event_rejects_wrong_secret():
    assert verify_event(_signed_event("events-secret"), "other-secret") is False


def test_wompi_disabled_without_credentials():
    assert WompiSandbox().enabled is False


def test_wompi_falls_back_to_fake_when_disabled():
    result = WompiSandbox().create_charge("ref-1", 1_000_000)
    assert result.provider == "fake"
    assert result.status == "APPROVED"
