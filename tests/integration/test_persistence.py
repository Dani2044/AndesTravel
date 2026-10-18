"""Persistence integration test.

Requires Postgres with pgvector. Skipped when Docker is unavailable and no
``TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from andes.core.enums import ConsentPurpose, MemoryKind
from andes.core.schemas import ConsentRecord, MemoryRecord, TravelerProfile
from andes.persistence import (
    AsyncConsentRepository,
    AsyncMemoryRepository,
    AsyncProfileRepository,
    create_all,
    drop_all,
    ensure_traveler,
    make_engine,
    make_sessionmaker,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
async def pg_engine() -> AsyncEngine:
    url = os.environ.get("TEST_DATABASE_URL")
    container = None
    if not url:
        try:
            from testcontainers.community.postgres import PostgresContainer  # noqa: PLC0415

            container = PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg")
            container.start()
            url = container.get_connection_url()
        except Exception as exc:  # pragma: no cover - depends on docker
            pytest.skip(f"docker unavailable: {exc}")
    engine = make_engine(url)
    try:
        await create_all(engine)
        yield engine
    finally:
        await drop_all(engine)
        await engine.dispose()
        if container is not None:  # pragma: no cover
            container.stop()


@pytest.fixture
async def session(pg_engine: AsyncEngine) -> AsyncSession:
    sessionmaker = make_sessionmaker(pg_engine)
    async with sessionmaker() as session:
        yield session


async def test_consent_roundtrip(session: AsyncSession) -> None:
    traveler_id = uuid4()
    await ensure_traveler(session, traveler_id)
    repo = AsyncConsentRepository(session)
    await repo.add(
        ConsentRecord(
            traveler_id=traveler_id,
            purpose=ConsentPurpose.QUOTATION,
            granted=True,
            evidence={"channel": "web"},
        )
    )
    assert await repo.active(traveler_id, ConsentPurpose.QUOTATION) is True
    assert len(await repo.history(traveler_id)) == 1


async def test_profile_merge_roundtrip(session: AsyncSession) -> None:
    traveler_id = uuid4()
    await ensure_traveler(session, traveler_id)
    repo = AsyncProfileRepository(session)
    await repo.upsert(
        TravelerProfile(traveler_id=traveler_id, attributes={"destination": "Cartagena"})
    )
    await repo.upsert(TravelerProfile(traveler_id=traveler_id, attributes={"party": 3}))
    profile = await repo.get(traveler_id)
    assert profile is not None
    assert profile.attributes == {"destination": "Cartagena", "party": 3}


async def test_memory_roundtrip(session: AsyncSession) -> None:
    traveler_id = uuid4()
    await ensure_traveler(session, traveler_id)
    repo = AsyncMemoryRepository(session)
    await repo.add(
        MemoryRecord(
            traveler_id=traveler_id,
            kind=MemoryKind.PREFERENCE,
            content="prefiere playa",
            embedding=[0.0] * 1024,
        )
    )
    memories = await repo.list(traveler_id)
    assert memories[0].content == "prefiere playa"


async def test_select_works(session: AsyncSession) -> None:
    result = await session.execute(text("SELECT 1"))
    assert result.scalar() == 1
    await session.commit()
