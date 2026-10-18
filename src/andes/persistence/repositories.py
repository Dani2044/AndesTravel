"""Async repository implementations (database-backed).

These satisfy the domain repository protocols by implementing the same method
signatures (async). The domain's in-memory implementations are used in tests; these
are exercised directly by integration tests against a real Postgres (via
testcontainers). The sync Protocol types in ``memory.repository`` are not bound to
these classes, so mypy compatibility is not required at the domain seam.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from andes.core.enums import ConsentPurpose
from andes.core.schemas import ConsentRecord, MemoryRecord, TravelerProfile
from andes.governance.audit import AuditRecord
from andes.governance.redact import redact_mapping
from andes.persistence.models import (
    AuditRow,
    ConsentRow,
    MemoryRow,
    ProfileRow,
    Traveler,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AsyncConsentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: ConsentRecord) -> None:
        row = ConsentRow(
            id=record.id,
            traveler_id=record.traveler_id,
            purpose=record.purpose.value,
            granted=record.granted,
            granted_at=record.granted_at,
            revoked_at=record.revoked_at,
            evidence=record.evidence,
        )
        self._session.add(row)

    async def history(self, traveler_id: UUID) -> list[ConsentRecord]:
        result = await self._session.execute(
            select(ConsentRow)
            .where(ConsentRow.traveler_id == traveler_id)
            .order_by(ConsentRow.granted_at)
        )
        return [self._to_schema(row) for row in result.scalars().all()]

    async def active(self, traveler_id: UUID, purpose: ConsentPurpose) -> bool:
        result = await self._session.execute(
            select(ConsentRow)
            .where(
                ConsentRow.traveler_id == traveler_id,
                ConsentRow.purpose == purpose.value,
            )
            .order_by(ConsentRow.granted_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return bool(row.granted) if row else False

    async def delete(self, traveler_id: UUID) -> None:
        await self._session.execute(delete(ConsentRow).where(ConsentRow.traveler_id == traveler_id))

    @staticmethod
    def _to_schema(row: ConsentRow) -> ConsentRecord:
        return ConsentRecord.model_validate(
            {
                "id": row.id,
                "traveler_id": row.traveler_id,
                "purpose": row.purpose,
                "granted": row.granted,
                "granted_at": row.granted_at,
                "revoked_at": row.revoked_at,
                "evidence": row.evidence,
            }
        )


class AsyncProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, profile: TravelerProfile) -> None:
        exists = await self._session.execute(
            select(ProfileRow).where(ProfileRow.traveler_id == profile.traveler_id)
        )
        if exists.scalar_one_or_none():
            await self._session.execute(
                update(ProfileRow)
                .where(ProfileRow.traveler_id == profile.traveler_id)
                .values(attributes=profile.attributes, updated_at=_utcnow())
            )
        else:
            row = ProfileRow(
                traveler_id=profile.traveler_id,
                attributes=profile.attributes,
                updated_at=profile.updated_at,
            )
            self._session.add(row)

    async def get(self, traveler_id: UUID) -> TravelerProfile | None:
        result = await self._session.execute(
            select(ProfileRow).where(ProfileRow.traveler_id == traveler_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return TravelerProfile.model_validate(
            {
                "traveler_id": row.traveler_id,
                "attributes": row.attributes,
                "updated_at": row.updated_at,
            }
        )

    async def delete(self, traveler_id: UUID) -> None:
        await self._session.execute(delete(ProfileRow).where(ProfileRow.traveler_id == traveler_id))


class AsyncMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: MemoryRecord) -> None:
        row = MemoryRow(
            id=record.id,
            traveler_id=record.traveler_id,
            kind=record.kind.value,
            content=record.content,
            channel=record.channel.value if record.channel else None,
            embedding=record.embedding,
            ts=record.ts,
        )
        self._session.add(row)

    async def list(self, traveler_id: UUID) -> list[MemoryRecord]:
        result = await self._session.execute(
            select(MemoryRow)
            .where(MemoryRow.traveler_id == traveler_id)
            .order_by(MemoryRow.ts.desc())
        )
        return [self._to_schema(row) for row in result.scalars().all()]

    async def delete(self, traveler_id: UUID) -> None:
        await self._session.execute(delete(MemoryRow).where(MemoryRow.traveler_id == traveler_id))

    @staticmethod
    def _to_schema(row: MemoryRow) -> MemoryRecord:
        return MemoryRecord.model_validate(
            {
                "id": row.id,
                "traveler_id": row.traveler_id,
                "kind": row.kind,
                "content": row.content,
                "channel": row.channel,
                "embedding": row.embedding,
                "ts": row.ts,
            }
        )


class AsyncAuditLog:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self, actor: str, action: str, entity: str, payload: dict[str, Any] | None = None
    ) -> AuditRecord:
        entry = AuditRecord(
            actor=actor,
            action=action,
            entity=entity,
            payload_redacted=redact_mapping(payload or {}),
        )
        row = AuditRow(
            id=entry.id,
            actor=entry.actor,
            action=entry.action,
            entity=entry.entity,
            payload_redacted=entry.payload_redacted,
            ts=entry.ts,
        )
        self._session.add(row)
        return entry

    async def entries(self) -> list[AuditRecord]:
        result = await self._session.execute(select(AuditRow).order_by(AuditRow.ts))
        return [
            AuditRecord.model_validate(
                {
                    "id": row.id,
                    "actor": row.actor,
                    "action": row.action,
                    "entity": row.entity,
                    "payload_redacted": row.payload_redacted,
                    "ts": row.ts,
                }
            )
            for row in result.scalars().all()
        ]


async def ensure_traveler(session: AsyncSession, traveler_id: UUID) -> None:
    result = await session.execute(select(Traveler).where(Traveler.id == traveler_id))
    if result.scalar_one_or_none() is None:
        session.add(Traveler(id=traveler_id))
        await session.flush()
