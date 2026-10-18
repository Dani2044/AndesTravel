"""Voice adapter for Twilio (Programmable Voice + speech recognition).

Inbound: Twilio form fields (``From``, ``To``, ``SpeechResult`` or ``Body``).
Outbound: TwiML consumed by the telephony provider. Speech-to-text and
text-to-speech run locally (faster-whisper + Piper) in the voice pipeline
(``TODO: wire the real provider credentials``).
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from andes.agents.assistant import AssistantReply
from andes.channels.base import traveler_id_from
from andes.core.enums import Channel
from andes.core.schemas import MessageEnvelope


class VoiceAdapter:
    channel = Channel.VOICE

    def parse(self, payload: dict) -> MessageEnvelope:
        sender = payload.get("From") or payload.get("from") or "unknown"
        text = payload.get("SpeechResult") or payload.get("Body") or payload.get("text") or ""
        return MessageEnvelope(
            traveler_id=traveler_id_from(sender),
            channel=self.channel,
            text=text,
            raw=payload,
        )

    def address(self, payload: dict) -> str:
        return str(payload.get("From") or payload.get("from") or "")

    def render(self, reply: AssistantReply, to: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Response><Say language="es-CO">'
            f"{escape(reply.text)}"
            "</Say></Response>"
        )
