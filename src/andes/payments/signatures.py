"""Wompi signature formulas (docs.wompi.co, Colombia).

Creation: SHA-256 over ``reference + amount_in_cents + currency + integrity_secret``.

Event: SHA-256 over the values of the properties the event lists in
``signature.properties`` (paths relative to ``data``, in that order), then the
``timestamp``, then the events secret. Checksums compare case-insensitively.
"""

from __future__ import annotations

import hashlib
from typing import Any

DEFAULT_CURRENCY = "COP"


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def integrity_signature(reference: str, amount_in_cents: int, currency: str, secret: str) -> str:
    return _sha256(f"{reference}{amount_in_cents}{currency}{secret}")


def _value_at_path(data: dict[str, Any], path: str) -> Any:
    """A missing hop resolves to an empty string rather than raising: a wrong signature must
    come back as False, not as an exception in the webhook."""
    current: Any = data
    for hop in path.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(hop)
    return "" if current is None else current


def event_signature(event: dict[str, Any], secret: str) -> str:
    signature = event.get("signature") or {}
    properties = signature.get("properties") or []
    data = event.get("data") or {}
    parts = [str(_value_at_path(data, path)) for path in properties]
    parts.append(str(event.get("timestamp", "")))
    return _sha256("".join(parts) + secret)


def verify_event(event: dict[str, Any], secret: str) -> bool:
    checksum = (event.get("signature") or {}).get("checksum")
    if not checksum:
        return False
    return event_signature(event, secret).lower() == str(checksum).lower()
