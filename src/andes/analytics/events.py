"""Product analytics events.

A deliberately small event model: named events with a traveler id, channel and
free-form properties. The gateway emits events per turn; metrics are derived in
``andes.analytics.metrics``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Event(BaseModel):
    name: str
    traveler_id: UUID | None = None
    channel: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_utcnow)


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...

    def events(self) -> list[Event]: ...


class InMemoryEventSink:
    def __init__(self) -> None:
        self._events: list[Event] = []

    def emit(self, event: Event) -> None:
        self._events.append(event)

    def events(self) -> list[Event]:
        return list(self._events)
