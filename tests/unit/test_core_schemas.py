from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from andes.core.enums import Channel, ConsentPurpose, ReservationStatus
from andes.core.schemas import MessageEnvelope, Quote, QuoteLine, TravelerProfile


def test_envelope_defaults_and_channel():
    env = MessageEnvelope(channel=Channel.WEB, text="Hola, quiero ir a Cartagena")
    assert env.channel == Channel.WEB
    assert env.locale == "es-CO"
    assert env.traveler_id is not None
    assert env.session_id is not None


def test_envelope_rejects_empty_text():
    with pytest.raises(ValidationError):
        MessageEnvelope(channel=Channel.WHATSAPP, text="   ")


def test_envelope_is_frozen():
    env = MessageEnvelope(channel=Channel.WEB, text="hola")
    with pytest.raises(ValidationError):
        env.text = "otro"  # type: ignore[misc]


def test_profile_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        TravelerProfile(traveler_id=uuid4(), unexpected=1)  # type: ignore[call-arg]


def test_consent_purpose_values():
    assert {p.value for p in ConsentPurpose} == {
        "personalization",
        "quotation",
        "booking",
    }


def test_quote_totals():
    q = Quote(
        traveler_id=uuid4(),
        package_id=uuid4(),
        lines=[QuoteLine(description="Base", amount=1000)],
        total_amount=1000,
        expires_at="2026-12-01T00:00:00Z",
    )
    assert q.total_amount == 1000
    assert q.currency == "COP"


def test_reservation_status_default_pending():
    assert ReservationStatus.PENDING.value == "pending"
