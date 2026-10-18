"""Append-only audit trail."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from andes.governance.redact import redact_mapping


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    actor: str
    action: str
    entity: str
    payload_redacted: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_utcnow)


class AuditLog(Protocol):
    def record(
        self, actor: str, action: str, entity: str, payload: dict[str, Any] | None = None
    ) -> AuditRecord: ...

    def entries(self) -> list[AuditRecord]: ...


class InMemoryAuditLog:
    """Process-local audit log (PII is redacted before storage)."""

    def __init__(self) -> None:
        self._entries: list[AuditRecord] = []

    def record(
        self, actor: str, action: str, entity: str, payload: dict[str, Any] | None = None
    ) -> AuditRecord:
        entry = AuditRecord(
            actor=actor,
            action=action,
            entity=entity,
            payload_redacted=redact_mapping(payload or {}),
        )
        self._entries.append(entry)
        return entry

    def entries(self) -> list[AuditRecord]:
        return list(self._entries)
