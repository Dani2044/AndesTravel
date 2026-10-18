"""Asynchronous text channels (email and SMS).

Both are thin JSON adapters around a generic message payload; the gateway
hands the rendered dict to the outbound provider (SMTP / SMS gateway).
"""

from __future__ import annotations

from andes.agents.assistant import AssistantReply
from andes.channels.base import traveler_id_from
from andes.core.enums import Channel
from andes.core.schemas import MessageEnvelope


class _TextAdapter:
    channel: Channel

    def parse(self, payload: dict) -> MessageEnvelope:
        sender = payload.get("from") or payload.get("address") or "unknown"
        return MessageEnvelope(
            traveler_id=traveler_id_from(sender),
            channel=self.channel,
            text=payload.get("text") or payload.get("body") or "",
            raw=payload,
        )

    def address(self, payload: dict) -> str:
        return str(payload.get("from") or payload.get("address") or "")

    def render(self, reply: AssistantReply, to: str) -> dict:
        return {"to": to, "channel": self.channel.value, "body": reply.text}


class EmailAdapter(_TextAdapter):
    channel = Channel.EMAIL


class SmsAdapter(_TextAdapter):
    channel = Channel.SMS
