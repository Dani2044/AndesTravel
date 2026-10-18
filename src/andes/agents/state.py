"""Shared state passed between LangGraph nodes."""

from __future__ import annotations

from typing import Any, TypedDict


class TravelerState(TypedDict, total=False):
    # Carried through the graph but not part of the domain contract.
    _envelope: Any
    _reply: Any
    traveler_id: str
    channel: str
    text: str
    intent: str
    profile: dict[str, Any]
    recommendations: list[dict[str, Any]]
    quote: dict[str, Any]
    reservation: dict[str, Any]
    handoff: dict[str, Any]
    response: str
    reason: str
