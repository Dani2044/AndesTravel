"""SQLAlchemy 2.0 models (the schema of record).

Embedding columns use pgvector (``Vector(1024)`` for bge-m3). The schema is created
by ``create_all`` for local runs and by Alembic in production.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


class Traveler(Base):
    __tablename__ = "travelers"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConsentRow(Base):
    __tablename__ = "consents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    traveler_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("travelers.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32))
    granted: Mapped[bool] = mapped_column(Boolean)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class ProfileRow(Base):
    __tablename__ = "profiles"

    traveler_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("travelers.id", ondelete="CASCADE"), primary_key=True
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryRow(Base):
    __tablename__ = "memories"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    traveler_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("travelers.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(16))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    package_id: Mapped[str] = mapped_column(String(64), index=True)
    destination: Mapped[str] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class AuditRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(128))
    payload_redacted: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReservationRow(Base):
    __tablename__ = "reservations"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    traveler_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    quote_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    total_amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="COP")
    commission_amount: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
