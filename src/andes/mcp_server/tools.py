"""Typed MCP tool implementations over the mock business systems.

These functions are the single integration boundary (see ``docs/mcp-contract.md``).
They validate inputs, return JSON-safe dicts, and never raise for expected domain
errors (they return an ``error`` object instead, matching the contract).
"""

from __future__ import annotations

from typing import Any

from andes.booking_api.store import BookingStore, get_store
from andes.core.errors import ValidationError
from andes.core.seed import find_package

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "check_availability": {
        "name": "check_availability",
        "description": "Return availability and current rate for a package.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package_id": {"type": "string"},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "travelers": {"type": "integer", "minimum": 1},
            },
            "required": ["package_id", "start_date", "end_date", "travelers"],
            "additionalProperties": False,
        },
    },
    "quote_package": {
        "name": "quote_package",
        "description": "Produce a structured quote with an explicit expiry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package_id": {"type": "string"},
                "travelers": {"type": "integer", "minimum": 1},
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "options": {"type": "object"},
            },
            "required": ["package_id", "travelers", "start_date", "end_date"],
            "additionalProperties": False,
        },
    },
    "create_reservation": {
        "name": "create_reservation",
        "description": "Create a reservation from an accepted, non-expired quote.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "string"},
                "traveler_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "payment": {"type": "object"},
            },
            "required": ["quote_id", "traveler_id", "idempotency_key"],
            "additionalProperties": False,
        },
    },
}


def _store_or_default(store: BookingStore | None) -> BookingStore:
    return store or get_store()


def check_availability(
    package_id: str,
    start_date: str,
    end_date: str,
    travelers: int,
    *,
    store: BookingStore | None = None,
) -> dict:
    if find_package(package_id) is None:
        raise ValidationError(f"unknown package_id: {package_id}")
    if travelers < 1:
        raise ValidationError("travelers must be >= 1")
    return _store_or_default(store).availability(package_id, start_date, end_date, travelers)


def quote_package(
    package_id: str,
    travelers: int,
    start_date: str,
    end_date: str,
    options: dict | None = None,
    *,
    store: BookingStore | None = None,
) -> dict:
    if find_package(package_id) is None:
        raise ValidationError(f"unknown package_id: {package_id}")
    if travelers < 1:
        raise ValidationError("travelers must be >= 1")
    return _store_or_default(store).quote(package_id, travelers, start_date, end_date, options)


def create_reservation(
    quote_id: str,
    traveler_id: str,
    idempotency_key: str,
    payment: dict | None = None,
    *,
    store: BookingStore | None = None,
) -> dict:
    if not idempotency_key:
        raise ValidationError("idempotency_key is required")
    return _store_or_default(store).create_reservation(
        quote_id, traveler_id, idempotency_key, payment
    )
