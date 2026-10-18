"""Application-level conversation service.

Ties together a channel adapter, the assistant, analytics and tracing. This is the
single entry point used by the API gateway (and by the worker for async channels).
"""

from __future__ import annotations

from typing import Any

from andes.agents.assistant import Assistant, AssistantReply
from andes.analytics.events import Event, EventSink
from andes.channels import ADAPTERS
from andes.channels.base import ChannelAdapter
from andes.core.enums import ConsentPurpose
from andes.memory.service import ConsentService
from andes.observability.tracing import NoopTracer, Tracer

_AUTO_CONSENT = (
    ConsentPurpose.PERSONALIZATION,
    ConsentPurpose.QUOTATION,
    ConsentPurpose.BOOKING,
)


class ConversationService:
    def __init__(
        self,
        *,
        assistant: Assistant,
        consent: ConsentService | None = None,
        events: EventSink | None = None,
        tracer: Tracer | None = None,
        adapters: dict[str, type[ChannelAdapter]] | None = None,
        auto_consent: bool = False,
    ) -> None:
        self._assistant = assistant
        self._consent = consent
        self._events = events
        self._tracer = tracer or NoopTracer()
        self._adapters = adapters or ADAPTERS
        self._auto_consent = auto_consent

    def _ensure_consent(self, traveler_id) -> None:
        if not (self._auto_consent and self._consent):
            return
        for purpose in _AUTO_CONSENT:
            if not self._consent.is_granted(traveler_id, purpose):
                self._consent.grant(traveler_id, purpose, {"source": "auto"})

    def handle(self, channel: str, payload: dict) -> Any:
        adapter_cls = self._adapters[channel]
        adapter = adapter_cls()
        envelope = adapter.parse(payload)
        self._ensure_consent(envelope.traveler_id)

        with self._tracer.span(
            "conversation.turn",
            {"channel": channel, "traveler_id": str(envelope.traveler_id)},
        ):
            reply = self._assistant.turn(envelope)

        self._emit(envelope, reply)
        return adapter.render(reply, adapter.address(payload))

    def _emit(self, envelope, reply: AssistantReply) -> None:
        if not self._events:
            return
        base: dict[str, Any] = {
            "traveler_id": envelope.traveler_id,
            "channel": envelope.channel.value,
        }
        self._events.emit(Event(name="turn.completed", **base))
        if reply.quote:
            self._events.emit(
                Event(
                    name="quote.created",
                    properties={"total_amount": reply.quote.total_amount},
                    **base,
                )
            )
        if reply.reservation:
            self._events.emit(
                Event(
                    name="reservation.created",
                    properties={"total_amount": reply.reservation.total_amount},
                    **base,
                )
            )
        if reply.handoff:
            self._events.emit(Event(name="handoff.created", **base))
