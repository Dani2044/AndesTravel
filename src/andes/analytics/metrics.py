"""Funnel metrics derived from analytics events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from andes.analytics.events import Event

_TURN = "turn.completed"
_QUOTE = "quote.created"
_RESERVATION = "reservation.created"
_HANDOFF = "handoff.created"


@dataclass(frozen=True)
class FunnelMetrics:
    turns: int
    quotes: int
    reservations: int
    handoffs: int

    @property
    def quote_rate(self) -> float:
        return self.quotes / self.turns if self.turns else 0.0

    @property
    def conversion_rate(self) -> float:
        return self.reservations / self.quotes if self.quotes else 0.0

    @property
    def handoff_rate(self) -> float:
        return self.handoffs / self.turns if self.turns else 0.0


def compute_funnel(events: Sequence[Event]) -> FunnelMetrics:
    counts = {_TURN: 0, _QUOTE: 0, _RESERVATION: 0, _HANDOFF: 0}
    for event in events:
        if event.name in counts:
            counts[event.name] += 1
    return FunnelMetrics(
        turns=counts[_TURN],
        quotes=counts[_QUOTE],
        reservations=counts[_RESERVATION],
        handoffs=counts[_HANDOFF],
    )
