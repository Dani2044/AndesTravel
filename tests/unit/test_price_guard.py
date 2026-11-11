"""Output guardrail: an amount reaches the traveler only if a quote backs it."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from andes.apps.tools_api import price_guard as pg
from andes.apps.tools_api.main import create_app
from andes.apps.tools_api.repository import MemoryRepository

KEY = "test-key"
H = {"X-API-Key": KEY}
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def _payload(text: str, tool_calls: object = None) -> dict:
    out: dict = {
        "agent_id": "a1",
        "messages": [{"role": "assistant", "content": {"type": "text", "text": text}}],
    }
    if tool_calls is not None:
        out["tool_calls"] = tool_calls
    return out


@pytest.mark.parametrize(
    ("text", "amounts"),
    [
        ("Total: 5.600.000 COP", {5_600_000}),
        ("Total: COP 11 200 000", {11_200_000}),
        ("Total: $5 200 000", {5_200_000}),
        ("Cuesta 12,600,000 pesos", {12_600_000}),
        ("Unos 3 millones por persona", {3_000_000}),
        ("Son 2,5 millones", {2_500_000}),
        ("Total $5600000", {5_600_000}),
        ("Sales el 2027-02-08, 4 días, 60 minutos, 3 personas", set()),
        ("Tu número 3103103108 y la reserva 91a890df-85c1-47cb", set()),
    ],
)
def test_amounts_in(text: str, amounts: set[int]) -> None:
    assert pg.amounts_in(text) == amounts


def test_unbacked_trusts_only_stored_quotes() -> None:
    assert pg.unbacked(_payload("Total 5.600.000 COP"), {5_600_000}) == set()
    assert pg.unbacked(_payload("Total 12.600.000 COP"), {5_600_000}) == {12_600_000}
    # knowledge-base text or LLM-written arguments in tool_calls never back a price
    kb = [{"name": "andes_catalog_kb", "result": "desde 6.500.000 COP por persona"}]
    assert pg.unbacked(_payload("Desde 6.500.000 COP", kb), set()) == {6_500_000}
    assert pg.unbacked(_payload("Sin precios aquí"), set()) == set()


def test_replace_answer_keeps_shape() -> None:
    payload = _payload("Total 12.600.000 COP")
    payload["messages"].append({"role": "assistant", "content": {"type": "text", "text": "x"}})
    out = pg.replace_answer(payload)
    assert [m["content"]["text"] for m in out["messages"]] == [pg.SAFE_MESSAGE]
    assert payload["messages"][0]["content"]["text"] == "Total 12.600.000 COP"  # not mutated


def test_shape_hides_values() -> None:
    assert pg.shape({"messages": [{"content": {"text": "secreto"}}]}) == {
        "messages": [{"content": {"text": "str[7]"}}, "len=1"]
    }


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(repo=MemoryRepository(), api_key=KEY, clock=lambda: NOW))


def _guard(client: TestClient, payload: dict) -> dict:
    r = client.post("/plugins/price_guard", json={"payload": payload, "context": {}}, headers=H)
    assert r.status_code == 200
    return r.json()


def test_route_blocks_invented_price_and_allows_quoted(client: TestClient) -> None:
    q = client.post(
        "/quotes",
        json={
            "traveler_id": "ana@example.com",
            "package": "Medellín",
            "start_date": "2026-12-10",
            "end_date": "2026-12-12",
            "travelers": 2,
        },
        headers=H,
    ).json()
    assert q["ok"] and q["total"]["amount"] == 5_600_000
    assert _guard(client, _payload("Total: 5.600.000 COP")) == {"continue_processing": True}
    assert _guard(client, _payload("Cada uno 2.800.000 COP")) == {"continue_processing": True}
    blocked = _guard(client, _payload("Total: 12.600.000 COP, válida 48 horas"))
    assert blocked["continue_processing"] is True
    assert blocked["modified_payload"]["messages"][0]["content"]["text"] == pg.SAFE_MESSAGE


def test_route_leaves_unknown_payloads_alone(client: TestClient) -> None:
    assert _guard(client, {"something": "else"}) == {"continue_processing": True}
    assert _guard(client, _payload("Hola, ¿a dónde quieres viajar?")) == {
        "continue_processing": True
    }


def test_route_requires_key(client: TestClient) -> None:
    r = client.post("/plugins/price_guard", json={"payload": {}, "context": {}})
    assert r.status_code == 401


def test_route_is_a_post_invoke_plugin(client: TestClient) -> None:
    op = client.get("/openapi.json").json()["paths"]["/plugins/price_guard"]["post"]
    assert op["x-ibm-orchestrate-plugin"] == {"hook": "agent_post_invoke"}
