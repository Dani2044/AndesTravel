"""Base interface and helpers for L1 channel adapters.

Every adapter translates a provider-specific payload into the channel-agnostic
:class:`MessageEnvelope` and renders an :class:`AssistantReply` back to the
provider's wire format. Adapters contain no business logic.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID, uuid5

from andes.agents.assistant import AssistantReply
from andes.core.enums import Channel
from andes.core.schemas import MessageEnvelope


def traveler_id_from(handle: str) -> UUID:
    """Map an external handle (phone, email, ...) to a stable traveler UUID."""

    return uuid5(NAMESPACE_URL, handle.strip().lower())


NAMESPACE_URL = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


class ChannelAdapter(Protocol):
    channel: Channel

    def parse(self, payload: dict) -> MessageEnvelope: ...

    def address(self, payload: dict) -> str: ...

    def render(self, reply: AssistantReply, to: str) -> dict | str: ...
