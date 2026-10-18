"""Repository abstractions and in-memory implementations.

The protocols are the seam between the domain services and the database. Production
uses the SQLAlchemy/Postgres implementations; unit tests use the in-memory ones.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from andes.core.enums import ConsentPurpose
from andes.core.schemas import ConsentRecord, MemoryRecord, TravelerProfile


class ConsentRepository(Protocol):
    def add(self, record: ConsentRecord) -> None: ...

    def history(self, traveler_id: UUID) -> list[ConsentRecord]: ...

    def active(self, traveler_id: UUID, purpose: ConsentPurpose) -> bool: ...

    def delete(self, traveler_id: UUID) -> None: ...


class ProfileRepository(Protocol):
    def upsert(self, profile: TravelerProfile) -> None: ...

    def get(self, traveler_id: UUID) -> TravelerProfile | None: ...

    def delete(self, traveler_id: UUID) -> None: ...


class MemoryRepository(Protocol):
    def add(self, record: MemoryRecord) -> None: ...

    def list(self, traveler_id: UUID) -> list[MemoryRecord]: ...

    def delete(self, traveler_id: UUID) -> None: ...


class InMemoryConsentRepository:
    def __init__(self) -> None:
        self._rows: list[ConsentRecord] = []

    def add(self, record: ConsentRecord) -> None:
        self._rows.append(record)

    def history(self, traveler_id: UUID) -> list[ConsentRecord]:
        return [r for r in self._rows if r.traveler_id == traveler_id]

    def active(self, traveler_id: UUID, purpose: ConsentPurpose) -> bool:
        relevant = [r for r in self._rows if r.traveler_id == traveler_id and r.purpose == purpose]
        if not relevant:
            return False
        latest = max(relevant, key=lambda r: r.granted_at)
        return latest.granted

    def delete(self, traveler_id: UUID) -> None:
        self._rows = [r for r in self._rows if r.traveler_id != traveler_id]


class InMemoryProfileRepository:
    def __init__(self) -> None:
        self._rows: dict[UUID, TravelerProfile] = {}

    def upsert(self, profile: TravelerProfile) -> None:
        self._rows[profile.traveler_id] = profile

    def get(self, traveler_id: UUID) -> TravelerProfile | None:
        return self._rows.get(traveler_id)

    def delete(self, traveler_id: UUID) -> None:
        self._rows.pop(traveler_id, None)


class InMemoryMemoryRepository:
    def __init__(self) -> None:
        self._rows: list[MemoryRecord] = []

    def add(self, record: MemoryRecord) -> None:
        self._rows.append(record)

    def list(self, traveler_id: UUID) -> list[MemoryRecord]:
        return [r for r in self._rows if r.traveler_id == traveler_id]

    def delete(self, traveler_id: UUID) -> None:
        self._rows = [r for r in self._rows if r.traveler_id != traveler_id]
