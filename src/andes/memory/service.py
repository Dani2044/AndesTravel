"""Consent, profile and memory services plus ARCO operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from andes.core.enums import ConsentPurpose
from andes.core.errors import ConsentRequired
from andes.core.schemas import ConsentRecord, TravelerProfile
from andes.governance.audit import AuditLog
from andes.memory.repository import (
    ConsentRepository,
    MemoryRepository,
    ProfileRepository,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ConsentService:
    """Purpose-bound consent with a traceable evidence trail."""

    def __init__(self, repo: ConsentRepository, audit: AuditLog | None = None) -> None:
        self._repo = repo
        self._audit = audit

    def grant(
        self,
        traveler_id: UUID,
        purpose: ConsentPurpose,
        evidence: dict[str, Any] | None = None,
    ) -> ConsentRecord:
        record = ConsentRecord(
            traveler_id=traveler_id,
            purpose=purpose,
            granted=True,
            evidence=evidence or {},
        )
        self._repo.add(record)
        if self._audit:
            self._audit.record(
                actor=str(traveler_id),
                action="consent.grant",
                entity=f"consent:{purpose}",
                payload=evidence,
            )
        return record

    def revoke(self, traveler_id: UUID, purpose: ConsentPurpose) -> ConsentRecord:
        record = ConsentRecord(
            traveler_id=traveler_id,
            purpose=purpose,
            granted=False,
            revoked_at=_utcnow(),
        )
        self._repo.add(record)
        if self._audit:
            self._audit.record(
                actor=str(traveler_id),
                action="consent.revoke",
                entity=f"consent:{purpose}",
            )
        return record

    def is_granted(self, traveler_id: UUID, purpose: ConsentPurpose) -> bool:
        return self._repo.active(traveler_id, purpose)

    def require(self, traveler_id: UUID, purpose: ConsentPurpose) -> None:
        if not self.is_granted(traveler_id, purpose):
            raise ConsentRequired(f"consent '{purpose}' not granted for {traveler_id}")

    def history(self, traveler_id: UUID) -> list[ConsentRecord]:
        return self._repo.history(traveler_id)


class ProfileService:
    """Minimized traveler profile with merge semantics."""

    def __init__(self, repo: ProfileRepository, audit: AuditLog | None = None) -> None:
        self._repo = repo
        self._audit = audit

    def update(self, traveler_id: UUID, attributes: dict[str, Any]) -> TravelerProfile:
        existing = self._repo.get(traveler_id)
        merged: dict[str, Any] = dict(existing.attributes) if existing else {}
        merged.update(attributes)
        profile = TravelerProfile(traveler_id=traveler_id, attributes=merged, updated_at=_utcnow())
        self._repo.upsert(profile)
        if self._audit:
            self._audit.record(
                actor=str(traveler_id),
                action="profile.update",
                entity=f"profile:{traveler_id}",
                payload=attributes,
            )
        return profile

    def get(self, traveler_id: UUID) -> TravelerProfile | None:
        return self._repo.get(traveler_id)

    def delete(self, traveler_id: UUID) -> None:
        self._repo.delete(traveler_id)


class MemoryService:
    """Facade over profile, memory and consent, including ARCO erasure."""

    def __init__(
        self,
        *,
        consent: ConsentService,
        profile: ProfileService,
        memory: MemoryRepository,
        audit: AuditLog | None = None,
    ) -> None:
        self.consent = consent
        self.profile = profile
        self._memory = memory
        self._audit = audit

    def erase(self, traveler_id: UUID) -> None:
        """Right to erasure: remove personal rows, keep a redacted audit entry."""

        self.profile.delete(traveler_id)
        self._memory.delete(traveler_id)
        if self._audit:
            self._audit.record(
                actor=str(traveler_id),
                action="traveler.erase",
                entity=f"traveler:{traveler_id}",
            )
