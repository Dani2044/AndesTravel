"""In-memory mock of the external business systems.

This is the ``L4 API mock`` from the architecture: availability, rates and
reservations. It is intentionally dependency-free so the whole system (and its
tests) can run offline. ``TODO(human)``: replace with real supplier integrations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from andes.core.seed import COMMISSION_RATE, find_package


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BookingStore:
    """Availability, quotation and reservations over the shared seed catalog."""

    def __init__(self, quote_ttl_minutes: int = 60) -> None:
        self._quote_ttl = timedelta(minutes=quote_ttl_minutes)
        self._quotes: dict[str, dict] = {}
        self._reservations: dict[str, dict] = {}
        self._by_idempotency: dict[str, str] = {}

    # -- availability ------------------------------------------------------
    def availability(self, package_id: str, start_date: str, end_date: str, travelers: int) -> dict:
        package = find_package(package_id)
        if package is None:
            return {"error": {"code": "not_found", "message": "package not found"}}
        if travelers < 1:
            return {"error": {"code": "invalid_dates", "message": "travelers must be >= 1"}}
        return {
            "available": True,
            "rate": {"amount": package["base_rate"], "currency": "COP"},
            "supplier": "andes-supplier-01",
            "fetched_at": _utcnow().isoformat(),
        }

    # -- quotation ---------------------------------------------------------
    def quote(
        self,
        package_id: str,
        travelers: int,
        start_date: str,
        end_date: str,
        options: dict | None = None,
    ) -> dict:
        availability = self.availability(package_id, start_date, end_date, travelers)
        if "error" in availability:
            return availability
        base = availability["rate"]["amount"]
        lines: list[dict[str, Any]] = [{"description": "Base package", "amount": base}]
        options = options or {}
        if options.get("include_insurance"):
            lines.append({"description": "Insurance", "amount": 180_000})
        total = sum(line["amount"] for line in lines)
        quote: dict[str, Any] = {
            "quote_id": str(uuid4()),
            "package_id": package_id,
            "lines": lines,
            "total": {"amount": total, "currency": "COP"},
            "expires_at": (_utcnow() + self._quote_ttl).isoformat(),
        }
        self._quotes[quote["quote_id"]] = quote
        return quote

    def get_quote(self, quote_id: str) -> dict | None:
        return self._quotes.get(quote_id)

    # -- reservations ------------------------------------------------------
    def create_reservation(
        self,
        quote_id: str,
        traveler_id: str,
        idempotency_key: str,
        payment: dict | None = None,
    ) -> dict:
        if idempotency_key in self._by_idempotency:
            existing_id = self._by_idempotency[idempotency_key]
            return {**self._reservations[existing_id], "deduplicated": True}
        quote = self._quotes.get(quote_id)
        if quote is None:
            return {"error": {"code": "not_found", "message": "quote not found"}}
        expires_at = datetime.fromisoformat(quote["expires_at"])
        if expires_at < _utcnow():
            return {"error": {"code": "quote_expired", "message": "quote expired"}}
        total = quote["total"]["amount"]
        reservation_id = str(uuid4())
        reservation = {
            "reservation_id": reservation_id,
            "traveler_id": traveler_id,
            "quote_id": quote_id,
            "status": "confirmed",
            "totals": {
                "amount": total,
                "currency": quote["total"]["currency"],
                "commission": int(total * COMMISSION_RATE),
            },
        }
        self._reservations[reservation_id] = reservation
        self._by_idempotency[idempotency_key] = reservation_id
        return reservation


_STORE: BookingStore | None = None


def get_store() -> BookingStore:
    global _STORE
    if _STORE is None:
        _STORE = BookingStore()
    return _STORE


def reset_store() -> None:
    """Test helper: drop all in-memory state."""

    global _STORE
    _STORE = BookingStore()
