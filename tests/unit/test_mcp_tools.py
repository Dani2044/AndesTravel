from __future__ import annotations

import pytest

from andes.core.errors import ValidationError
from andes.mcp_server.tools import (
    TOOL_SCHEMAS,
    check_availability,
    create_reservation,
    quote_package,
)


def test_schemas_expose_required_fields():
    for name, schema in TOOL_SCHEMAS.items():
        assert schema["name"] == name
        assert schema["inputSchema"]["type"] == "object"
        assert schema["inputSchema"]["required"]


def test_check_availability_ok(store):
    result = check_availability(
        "11111111-1111-1111-1111-111111111101", "2026-03-01", "2026-03-06", 2, store=store
    )
    assert result["available"] is True
    assert result["rate"]["currency"] == "COP"


def test_check_availability_unknown_package(store):
    with pytest.raises(ValidationError):
        check_availability("missing", "2026-03-01", "2026-03-06", 2, store=store)


def test_check_availability_rejects_zero_travelers(store):
    with pytest.raises(ValidationError):
        check_availability("11111111-1111-1111-1111-111111111101", "a", "b", 0, store=store)


def test_quote_includes_insurance(store):
    result = quote_package(
        "11111111-1111-1111-1111-111111111101",
        2,
        "2026-03-01",
        "2026-03-06",
        {"include_insurance": True},
        store=store,
    )
    assert len(result["lines"]) == 2
    assert result["total"]["amount"] == sum(line["amount"] for line in result["lines"])


def test_reservation_is_idempotent(store):
    quote = quote_package(
        "11111111-1111-1111-1111-111111111102", 2, "2026-03-01", "2026-03-05", store=store
    )
    first = create_reservation(quote["quote_id"], "traveler-1", "key-1", store=store)
    second = create_reservation(quote["quote_id"], "traveler-1", "key-1", store=store)
    assert first["reservation_id"] == second["reservation_id"]
    assert second["deduplicated"] is True


def test_reservation_unknown_quote(store):
    result = create_reservation("missing", "traveler-1", "key-2", store=store)
    assert result["error"]["code"] == "not_found"


def test_reservation_requires_idempotency_key(store):
    with pytest.raises(ValidationError):
        create_reservation("x", "traveler-1", "", store=store)
