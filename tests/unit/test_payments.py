"""Payment providers: Wompi signatures, the real sandbox adapter, the fake.

The two signature formulas below are the ones docs.wompi.co specifies for
Colombia. They are pinned as pure functions on purpose: if someone changes the
concatenation order, a test should break here instead of a real charge.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest
import respx

from andes.core.config import Settings
from andes.payments import FakePaymentProvider, payment_provider_from_settings
from andes.payments.wompi import (
    SANDBOX_URL,
    WompiSandbox,
    event_signature,
    integrity_signature,
    parse_event,
    verify_event,
)


@pytest.mark.asyncio
async def test_fake_provider_approves() -> None:
    result = await FakePaymentProvider().create_charge("ref-1", 5_000_000)
    assert result.provider == "fake"
    assert result.status == "APPROVED"
    assert result.amount == 5_000_000


def test_integrity_signature_is_the_documented_hash() -> None:
    expected = hashlib.sha256(b"ref-1250000COPsecret").hexdigest()
    assert integrity_signature("ref-1", 250_000, "COP", "secret") == expected


def test_integrity_signature_treats_the_amount_as_cents() -> None:
    assert integrity_signature("ref-1", 250_000, "COP", "s") != integrity_signature(
        "ref-1", 2_500, "COP", "s"
    )


def _event(status: str = "APPROVED", timestamp: int = 1_700_000_000) -> dict:
    return {
        "id": "evt-9",
        "event": "transaction.updated",
        "timestamp": timestamp,
        "data": {"transaction": {"id": "txn-9", "reference": "ref-9", "status": status}},
        "signature": {"properties": ["transaction.id", "transaction.status"]},
    }


def test_event_signature_reads_properties_inside_data_then_timestamp_then_secret() -> None:
    expected = hashlib.sha256(b"txn-9APPROVED1700000000events").hexdigest()
    assert event_signature(_event(), "events") == expected


def test_event_signature_respects_the_order_declared_by_the_event() -> None:
    event = _event()
    event["signature"]["properties"] = ["transaction.status", "transaction.id"]
    expected = hashlib.sha256(b"APPROVEDtxn-91700000000events").hexdigest()
    assert event_signature(event, "events") == expected


def test_event_signature_blank_fills_a_property_the_body_does_not_carry() -> None:
    event = _event()
    event["signature"]["properties"] = ["transaction.nope", "transaction.status"]
    expected = hashlib.sha256(b"APPROVED1700000000events").hexdigest()
    assert event_signature(event, "events") == expected


def test_verify_event_accepts_a_valid_checksum_regardless_of_case() -> None:
    event = _event()
    event["signature"]["checksum"] = event_signature(event, "events-secret").upper()
    assert verify_event(event, "events-secret") is True


def test_verify_event_rejects_the_wrong_secret() -> None:
    event = _event()
    event["signature"]["checksum"] = event_signature(event, "events-secret")
    assert verify_event(event, "other-secret") is False


def test_verify_event_rejects_a_body_edited_after_signing() -> None:
    event = _event()
    event["signature"]["checksum"] = event_signature(event, "events-secret")
    event["data"]["transaction"]["status"] = "DECLINED"
    assert verify_event(event, "events-secret") is False


def test_verify_event_rejects_an_event_without_checksum() -> None:
    assert verify_event(_event(), "events-secret") is False


@pytest.mark.parametrize(
    ("wompi_status", "expected"),
    [
        ("APPROVED", "APPROVED"),
        ("PENDING", "PENDING"),
        ("DECLINED", "DECLINED"),
        ("VOIDED", "DECLINED"),
        ("ERROR", "DECLINED"),
        (None, "PENDING"),
    ],
)
def test_parse_event_translates_wompi_statuses(wompi_status: str | None, expected: str) -> None:
    event = _event(status=wompi_status) if wompi_status is not None else _event()
    if wompi_status is None:
        del event["data"]["transaction"]["status"]
    parsed = parse_event(event)
    assert parsed.status == expected
    assert parsed.reference == "ref-9"
    assert parsed.transaction_id == "txn-9"


def test_parse_event_falls_back_to_the_transaction_id_when_there_is_no_event_id() -> None:
    event = _event()
    del event["id"]
    assert parse_event(event).event_id == "txn-9"


@pytest.mark.asyncio
@respx.mock
async def test_sandbox_fetches_the_acceptance_token_then_creates_the_transaction() -> None:
    respx.get(f"{SANDBOX_URL}/merchants/info").respond(
        200, json={"data": {"presigned_acceptance": {"acceptance_token": "tok-1"}}}
    )
    route = respx.post(f"{SANDBOX_URL}/transactions").respond(
        200, json={"data": {"id": "txn-42", "status": "PENDING"}}
    )

    provider = WompiSandbox(
        public_key="pk_test",
        private_key="sk_test",
        events_secret="ev_test",
        integrity_secret="in_test",
    )
    result = await provider.create_charge("ref-42", 1_500_000, email="ana@example.com")

    assert result.provider == "wompi"
    assert result.transaction_id == "txn-42"
    assert result.status == "PENDING"
    assert route.calls.last.request.headers["authorization"] == "Bearer sk_test"
    sent = route.calls.last.request.read().replace(b" ", b"")
    assert b'"acceptance_token":"tok-1"' in sent
    assert integrity_signature("ref-42", 1_500_000, "COP", "in_test").encode() in sent


@pytest.mark.asyncio
@respx.mock
async def test_sandbox_sends_the_redirect_url_when_one_is_given() -> None:
    respx.get(f"{SANDBOX_URL}/merchants/info").respond(
        200, json={"data": {"presigned_acceptance": {"acceptance_token": "tok-1"}}}
    )
    route = respx.post(f"{SANDBOX_URL}/transactions").respond(
        200,
        json={
            "data": {"id": "txn-7", "status": "PENDING", "redirect_url": "https://pay.example/7"}
        },
    )

    provider = WompiSandbox(
        public_key="pk", private_key="sk", events_secret="ev", integrity_secret="in"
    )
    result = await provider.create_charge(
        "ref-7", 90_000, email="ana@example.com", redirect_url="https://andes.travel/pay"
    )

    assert result.redirect_url == "https://pay.example/7"
    assert b"andes.travel/pay" in route.calls.last.request.read()


@pytest.mark.asyncio
@respx.mock
async def test_sandbox_surfaces_a_declined_charge() -> None:
    respx.get(f"{SANDBOX_URL}/merchants/info").respond(
        200, json={"data": {"presigned_acceptance": {"acceptance_token": "tok-1"}}}
    )
    respx.post(f"{SANDBOX_URL}/transactions").respond(
        200, json={"data": {"id": "txn-8", "status": "DECLINED"}}
    )

    provider = WompiSandbox(
        public_key="pk", private_key="sk", events_secret="ev", integrity_secret="in"
    )
    result = await provider.create_charge("ref-8", 90_000, email="ana@example.com")
    assert result.status == "DECLINED"


@pytest.mark.asyncio
@respx.mock
async def test_sandbox_raises_when_wompi_answers_with_an_error() -> None:
    respx.get(f"{SANDBOX_URL}/merchants/info").respond(
        200, json={"data": {"presigned_acceptance": {"acceptance_token": "tok-1"}}}
    )
    respx.post(f"{SANDBOX_URL}/transactions").respond(422, json={"error": {"message": "bad"}})

    provider = WompiSandbox(
        public_key="pk", private_key="sk", events_secret="ev", integrity_secret="in"
    )
    with pytest.raises(httpx.HTTPStatusError):
        await provider.create_charge("ref-9", 90_000, email="ana@example.com")


def test_the_fake_signs_events_the_real_way() -> None:
    fake = FakePaymentProvider()
    event = fake.signed_event(reference="ref-1", transaction_id="txn-1", status="APPROVED")
    assert verify_event(event, fake.events_secret) is True
    event["data"]["transaction"]["status"] = "DECLINED"
    assert verify_event(event, fake.events_secret) is False


def test_provider_factory_returns_the_fake_by_default() -> None:
    provider = payment_provider_from_settings(Settings())
    assert isinstance(provider, FakePaymentProvider)


def test_provider_factory_returns_wompi_in_sandbox_mode() -> None:
    settings = Settings(
        wompi_mode="sandbox",
        wompi_public_key="pk",
        wompi_private_key="sk",
        wompi_events_secret="ev",
        wompi_integrity_secret="in",
    )
    provider = payment_provider_from_settings(settings)
    assert isinstance(provider, WompiSandbox)
    assert provider.enabled is True


def test_provider_factory_fails_loudly_when_sandbox_is_half_configured() -> None:
    settings = Settings(wompi_mode="sandbox", wompi_public_key="pk")
    with pytest.raises(RuntimeError, match="wompi_private_key"):
        payment_provider_from_settings(settings)
