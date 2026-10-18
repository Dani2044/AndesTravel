"""WhatsApp adapter for the Meta Cloud API webhook.

Inbound: the ``messages`` array of the first ``entry[].changes[].value``.
Outbound: the ``/messages`` text payload (sent by the gateway via httpx).

``TODO``: verify the sender signature (``X-Hub-Signature-256``) before
trusting the payload, and set the real phone-number id / access token.
"""

from __future__ import annotations

from andes.agents.assistant import AssistantReply
from andes.channels.base import traveler_id_from
from andes.core.enums import Channel
from andes.core.schemas import MessageEnvelope


class WhatsAppAdapter:
    channel = Channel.WHATSAPP

    def parse(self, payload: dict) -> MessageEnvelope:
        value = payload["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
        sender = message["from"]
        if message.get("type") == "text":
            text = message["text"]["body"]
        elif message.get("type") == "button":
            text = message["button"].get("text", "")
        else:
            text = message.get("text", {}).get("body", "")
        return MessageEnvelope(
            traveler_id=traveler_id_from(sender),
            channel=self.channel,
            text=text,
            raw=payload,
        )

    def address(self, payload: dict) -> str:
        value = payload["entry"][0]["changes"][0]["value"]
        return value["messages"][0]["from"]

    def render(self, reply: AssistantReply, to: str) -> dict:
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": reply.text},
        }
