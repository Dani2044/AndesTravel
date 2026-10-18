from __future__ import annotations

from uuid import uuid4

from andes.analytics.events import Event, InMemoryEventSink
from andes.analytics.metrics import compute_funnel


def test_emit_and_list():
    sink = InMemoryEventSink()
    sink.emit(Event(name="turn.completed", traveler_id=uuid4(), channel="web"))
    assert len(sink.events()) == 1


def test_funnel_metrics():
    sink = InMemoryEventSink()
    traveler = uuid4()
    for name in ("turn.completed", "turn.completed", "turn.completed"):
        sink.emit(Event(name=name, traveler_id=traveler, channel="web"))
    sink.emit(Event(name="quote.created", traveler_id=traveler))
    sink.emit(Event(name="reservation.created", traveler_id=traveler))
    metrics = compute_funnel(sink.events())
    assert metrics.turns == 3
    assert metrics.quotes == 1
    assert metrics.reservations == 1
    assert metrics.quote_rate == 1 / 3
    assert metrics.conversion_rate == 1.0


def test_empty_funnel():
    metrics = compute_funnel([])
    assert metrics.turns == 0
    assert metrics.conversion_rate == 0.0
