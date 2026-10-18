"""Pydantic domain schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from andes.core.enums import (
    Channel,
    ConsentPurpose,
    Intent,
    MemoryKind,
    ReservationStatus,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MessageEnvelope(BaseModel):
    """Channel-agnostic inbound message produced by every L1 adapter."""

    model_config = ConfigDict(frozen=True)

    traveler_id: UUID = Field(default_factory=uuid4)
    channel: Channel
    session_id: UUID = Field(default_factory=uuid4)
    text: str
    attachments: list[str] = Field(default_factory=list)
    locale: str = "es-CO"
    received_at: datetime = Field(default_factory=_utcnow)
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("text must not be empty")
        return value


class TravelerProfile(BaseModel):
    """Minimized traveler profile."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: UUID
    attributes: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=_utcnow)


class ConsentRecord(BaseModel):
    """A single consent lifecycle event."""

    id: UUID = Field(default_factory=uuid4)
    traveler_id: UUID
    purpose: ConsentPurpose
    granted: bool
    granted_at: datetime = Field(default_factory=_utcnow)
    revoked_at: datetime | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class MemoryRecord(BaseModel):
    """A long-term memory record, optionally embedded."""

    id: UUID = Field(default_factory=uuid4)
    traveler_id: UUID
    kind: MemoryKind
    content: str
    channel: Channel | None = None
    embedding: list[float] | None = None
    ts: datetime = Field(default_factory=_utcnow)


class QuoteLine(BaseModel):
    description: str
    amount: int  # minor units (COP has no decimals in practice)


class Quote(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    traveler_id: UUID
    package_id: UUID
    lines: list[QuoteLine]
    total_amount: int
    currency: str = "COP"
    expires_at: datetime


class Reservation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    traveler_id: UUID
    quote_id: UUID
    status: ReservationStatus = ReservationStatus.PENDING
    total_amount: int
    currency: str = "COP"
    commission_amount: int = 0
    idempotency_key: str
    created_at: datetime = Field(default_factory=_utcnow)


class PackageSummary(BaseModel):
    id: UUID
    destination: str
    name: str
    description: str
    duration_days: int
    tags: list[str] = Field(default_factory=list)
    score: float = 0.0


class HandoffSummary(BaseModel):
    """Structured context passed to a human advisor on escalation."""

    traveler_id: UUID
    intent: Intent
    reason: str
    profile: dict[str, Any] = Field(default_factory=dict)
    memory_highlights: list[str] = Field(default_factory=list)
    open_question: str | None = None
