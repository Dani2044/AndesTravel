"""Tools API against real Postgres, using the same SQL that is applied in Supabase.

Skipped when Docker is unavailable and ``TEST_DATABASE_URL`` is not set.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from andes.apps.tools_api.main import create_app
from andes.apps.tools_api.repository import PostgresRepository

pytestmark = pytest.mark.asyncio

ROOT = Path(__file__).resolve().parents[2]
KEY = "it-key"
H = {"X-API-Key": KEY}
NOW = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)
TABLES = "handoffs, reservations, quotes, traveler_profiles, travelers, packages"


@pytest.fixture(scope="module")
async def pg_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    container = None
    if url and "supabase" in url:
        pytest.fail(
            "TEST_DATABASE_URL points at Supabase; this test drops tables. Use a scratch DB."
        )
    if not url:
        try:
            from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415

            container = PostgresContainer("postgres:16-alpine", driver="asyncpg")
            container.start()
            url = container.get_connection_url()
        except Exception as exc:  # pragma: no cover - depends on docker
            pytest.skip(f"docker unavailable: {exc}")
    engine = create_async_engine(url)
    sql = (ROOT / "supabase/migrations/0001_init.sql").read_text() + (
        ROOT / "supabase/seed.sql"
    ).read_text()
    async with engine.begin() as conn:
        raw = await conn.get_raw_connection()
        await raw.driver_connection.execute(f"drop table if exists {TABLES} cascade")
        await raw.driver_connection.execute(sql)
    await engine.dispose()
    try:
        yield url
    finally:
        if container is not None:  # pragma: no cover
            container.stop()


@pytest.fixture
async def client(pg_url: str):
    repo = PostgresRepository(pg_url)
    app = create_app(repo=repo, api_key=KEY, clock=lambda: NOW)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await repo.close()


async def _quote(client: httpx.AsyncClient, traveler: str) -> dict:
    r = await client.post(
        "/quotes",
        json={
            "traveler_id": traveler,
            "package": "eje cafetero",
            "start_date": "2026-12-20",
            "end_date": "2026-12-25",
            "travelers": 3,
        },
        headers=H,
    )
    return r.json()


async def test_profile_roundtrip_and_erasure(client: httpx.AsyncClient) -> None:
    put = await client.put(
        "/travelers/pg@example.com/profile",
        json={
            "consent_personalization": True,
            "attributes": {"interests": ["café", "montaña"], "companions": "familia con niños"},
            "persona_prompt": "Familia con dos niños; prefiere clima templado y planes cortos.",
        },
        headers=H,
    )
    assert put.json()["stored"] is True
    ctx = (await client.get("/travelers/PG@example.com/context", headers=H)).json()
    assert ctx["persona_prompt"].startswith("Familia con dos niños")
    assert ctx["attributes"]["interests"] == ["café", "montaña"]
    await client.put(
        "/travelers/pg@example.com/profile", json={"consent_personalization": False}, headers=H
    )
    ctx = (await client.get("/travelers/pg@example.com/context", headers=H)).json()
    assert ctx["persona_prompt"] is None and ctx["attributes"] == {}


async def test_quote_and_concurrent_idempotent_booking(client: httpx.AsyncClient) -> None:
    q = await _quote(client, "booker@example.com")
    assert q["total"]["amount"] == 5_200_000 * 3
    body = {"traveler_id": "booker@example.com", "quote_id": q["quote_id"], "idempotency_key": "c1"}
    a, b = await asyncio.gather(
        client.post("/reservations", json=body, headers=H),
        client.post("/reservations", json=body, headers=H),
    )
    ra, rb = a.json(), b.json()
    assert ra["reservation_id"] == rb["reservation_id"]
    assert sorted([ra["deduplicated"], rb["deduplicated"]]) == [False, True]
    ctx = (await client.get("/travelers/booker@example.com/context", headers=H)).json()
    assert ctx["recent_reservations"][0]["destination"] == "Eje Cafetero"


async def test_other_traveler_cannot_book_or_see(client: httpx.AsyncClient) -> None:
    q = await _quote(client, "owner@example.com")
    r = await client.post(
        "/reservations",
        json={
            "traveler_id": "thief@example.com",
            "quote_id": q["quote_id"],
            "idempotency_key": "t",
        },
        headers=H,
    )
    assert r.json()["error"]["code"] == "quote_not_found"
    ctx = (await client.get("/travelers/thief@example.com/context", headers=H)).json()
    assert ctx["recent_reservations"] == []


async def test_handoff_persists(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/handoffs",
        json={"traveler_id": "3001234567", "reason": "upset", "summary": "Reclamo por demora."},
        headers=H,
    )
    assert r.json()["ok"] is True
