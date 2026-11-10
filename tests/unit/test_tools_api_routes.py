"""HTTP behaviour of the tools API over the in-memory repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from andes.apps.tools_api.main import create_app
from andes.apps.tools_api.repository import MemoryRepository

KEY = "test-key"
H = {"X-API-Key": KEY}
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(clock: Clock) -> TestClient:
    return TestClient(create_app(repo=MemoryRepository(), api_key=KEY, clock=clock))


def _quote(client: TestClient, traveler: str = "ana@example.com", **over) -> dict:
    body = {
        "traveler_id": traveler,
        "package": "Cartagena",
        "start_date": "2026-12-10",
        "end_date": "2026-12-14",
        "travelers": 2,
        "include_insurance": True,
        **over,
    }
    return client.post("/quotes", json=body, headers=H).json()


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "storage": "memory"}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_tools_require_api_key(client: TestClient, headers: dict) -> None:
    assert client.get("/travelers/ana@example.com/context", headers=headers).status_code == 401


def test_missing_server_key_is_503() -> None:
    app = create_app(repo=MemoryRepository(), api_key="")
    assert TestClient(app).post("/handoffs", json={}, headers=H).status_code == 503


def test_unknown_traveler_context(client: TestClient) -> None:
    body = client.get("/travelers/Nuevo@Example.com/context", headers=H).json()
    assert body["ok"] and body["traveler_id"] == "nuevo@example.com"
    assert body["known_traveler"] is False and body["persona_prompt"] is None
    assert body["today"] == "2026-11-09"  # NOW in Bogotá


def test_context_reports_today_even_on_invalid_id(client: TestClient) -> None:
    body = client.get("/travelers/no-es-un-id/context", headers=H).json()
    assert body["ok"] is False and body["today"] == "2026-11-09"


def test_profile_roundtrip_with_consent(client: TestClient) -> None:
    put = client.put(
        "/travelers/3001234567/profile",
        json={
            "consent_personalization": True,
            "attributes": {"travel_style": "descanso", "interests": ["playa"], "group_size": 2},
            "persona_prompt": "Viaja en pareja, prefiere playa y descanso.",
        },
        headers=H,
    ).json()
    assert put == {"ok": True, "error": None, "traveler_id": "+573001234567", "stored": True}
    ctx = client.get("/travelers/+573001234567/context", headers=H).json()
    assert ctx["consent_personalization"] is True
    assert ctx["persona_prompt"] == "Viaja en pareja, prefiere playa y descanso."
    assert ctx["attributes"]["interests"] == ["playa"]


def test_profile_without_consent_is_not_stored_and_erases(client: TestClient) -> None:
    client.put(
        "/travelers/ana@example.com/profile",
        json={"consent_personalization": True, "persona_prompt": "Le gusta el café."},
        headers=H,
    )
    revoke = client.put(
        "/travelers/ana@example.com/profile",
        json={"consent_personalization": False, "persona_prompt": "otra cosa"},
        headers=H,
    ).json()
    assert revoke["ok"] is False and revoke["error"]["code"] == "consent_required"
    ctx = client.get("/travelers/ana@example.com/context", headers=H).json()
    assert ctx["persona_prompt"] is None and ctx["attributes"] == {}


def test_availability_and_domain_errors(client: TestClient) -> None:
    ok = client.get(
        "/availability",
        params={
            "package": "tayrona",
            "start_date": "2026-12-01",
            "end_date": "2026-12-05",
            "travelers": 2,
        },
        headers=H,
    ).json()
    assert ok["ok"] and ok["available"] and ok["nights"] == 4
    assert ok["rate_per_person"] == {"amount": 3_900_000, "currency": "COP"}
    bad = client.get(
        "/availability",
        params={
            "package": "Marte",
            "start_date": "2026-12-01",
            "end_date": "2026-12-05",
            "travelers": 2,
        },
        headers=H,
    ).json()
    assert bad["ok"] is False and bad["error"]["code"] == "unknown_package"


def test_quote_prices_per_person_and_expires(client: TestClient) -> None:
    q = _quote(client)
    assert q["ok"] and q["travelers"] == 2
    assert q["total"] == {"amount": (4_800_000 + 180_000) * 2, "currency": "COP"}
    assert q["expires_at"] == (NOW + timedelta(minutes=60)).isoformat(timespec="seconds")


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"start_date": "2027-02-30"}, "invalid_dates"),
        ({"travelers": 3000}, "invalid_travelers"),
        ({"package": "Atlántida"}, "unknown_package"),
        ({"traveler_id": "no-soy-un-correo"}, "invalid_traveler_id"),
    ],
)
def test_quote_rejects_nonsense(client: TestClient, over: dict, code: str) -> None:
    q = _quote(client, **over)
    assert q["ok"] is False and q["error"]["code"] == code and q["total"] is None


def test_reservation_is_idempotent(client: TestClient) -> None:
    q = _quote(client)
    body = {"traveler_id": "ana@example.com", "quote_id": q["quote_id"], "idempotency_key": "k1"}
    first = client.post("/reservations", json=body, headers=H).json()
    again = client.post("/reservations", json=body, headers=H).json()
    assert first["ok"] and first["status"] == "confirmed" and not first["deduplicated"]
    assert again["reservation_id"] == first["reservation_id"] and again["deduplicated"]
    ctx = client.get("/travelers/ana@example.com/context", headers=H).json()
    assert ctx["known_traveler"] and ctx["recent_reservations"][0]["destination"] == "Cartagena"


def test_reservation_needs_own_unexpired_quote(client: TestClient, clock: Clock) -> None:
    q = _quote(client)
    other = client.post(
        "/reservations",
        json={"traveler_id": "eve@example.com", "quote_id": q["quote_id"], "idempotency_key": "x"},
        headers=H,
    ).json()
    assert other["error"]["code"] == "quote_not_found"
    missing = client.post(
        "/reservations",
        json={"traveler_id": "ana@example.com", "quote_id": "nope", "idempotency_key": "y"},
        headers=H,
    ).json()
    assert missing["error"]["code"] == "quote_not_found"
    clock.now = NOW + timedelta(minutes=61)
    expired = client.post(
        "/reservations",
        json={"traveler_id": "ana@example.com", "quote_id": q["quote_id"], "idempotency_key": "z"},
        headers=H,
    ).json()
    assert expired["error"]["code"] == "quote_expired"


def test_retry_after_expiry_returns_original_booking(client: TestClient, clock: Clock) -> None:
    q = _quote(client)
    body = {"traveler_id": "ana@example.com", "quote_id": q["quote_id"], "idempotency_key": "k"}
    first = client.post("/reservations", json=body, headers=H).json()
    clock.now = NOW + timedelta(hours=2)
    retry = client.post("/reservations", json=body, headers=H).json()
    assert retry["ok"] and retry["reservation_id"] == first["reservation_id"]
    assert retry["deduplicated"]


def test_idempotency_key_cannot_be_reused_for_another_quote(client: TestClient) -> None:
    q1, q2 = _quote(client), _quote(client, package="Bogotá")
    base = {"traveler_id": "ana@example.com", "idempotency_key": "same"}
    client.post("/reservations", json={**base, "quote_id": q1["quote_id"]}, headers=H)
    second = client.post("/reservations", json={**base, "quote_id": q2["quote_id"]}, headers=H)
    assert second.json()["error"]["code"] == "idempotency_conflict"


def test_handoff(client: TestClient) -> None:
    out = client.post(
        "/handoffs",
        json={
            "traveler_id": "ana@example.com",
            "reason": "asked_for_human",
            "summary": "Quiere cambiar fechas de su reserva a Cartagena.",
        },
        headers=H,
    ).json()
    assert out["ok"] and out["status"] == "queued" and out["handoff_id"]


def test_openapi_operation_ids_are_tool_names(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    ops = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert ops == {
        "get_traveler_context",
        "upsert_traveler_profile",
        "escalate_to_human",
        "check_availability",
        "quote_package",
        "create_reservation",
    }
