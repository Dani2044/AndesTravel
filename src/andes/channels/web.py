"""Web channel adapter."""

from __future__ import annotations

from uuid import UUID, uuid4

from andes.agents.assistant import AssistantReply
from andes.channels.base import traveler_id_from
from andes.core.enums import Channel
from andes.core.schemas import MessageEnvelope


class WebAdapter:
    channel = Channel.WEB

    def parse(self, payload: dict) -> MessageEnvelope:
        text = payload.get("text") or payload.get("message") or ""
        raw_id = payload.get("traveler_id")
        raw_session = payload.get("session_id")
        if raw_id:
            traveler_id = UUID(str(raw_id))
        elif handle := payload.get("handle"):
            traveler_id = traveler_id_from(str(handle))
        else:
            traveler_id = uuid4()
        session_id = UUID(str(raw_session)) if raw_session else uuid4()
        return MessageEnvelope(
            traveler_id=traveler_id,
            channel=self.channel,
            session_id=session_id,
            text=text,
            raw=payload,
        )

    def address(self, payload: dict) -> str:
        return str(payload.get("handle") or "")

    def render(self, reply: AssistantReply, to: str) -> dict:
        return {
            "text": reply.text,
            "intent": reply.intent.value,
            "recommendations": [s.model_dump(mode="json") for s in reply.recommendations],
            "quote": reply.quote.model_dump(mode="json") if reply.quote else None,
            "reservation": (
                reply.reservation.model_dump(mode="json") if reply.reservation else None
            ),
            "handoff": reply.handoff.model_dump(mode="json") if reply.handoff else None,
        }
