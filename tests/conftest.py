"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest

from andes.agents.assistant import Assistant
from andes.analytics.events import InMemoryEventSink
from andes.booking_api.store import BookingStore
from andes.conversation import ConversationService
from andes.core.enums import ConsentPurpose
from andes.governance.audit import InMemoryAuditLog
from andes.knowledge.embeddings import FakeEmbedder
from andes.knowledge.retriever import Retriever
from andes.memory.repository import (
    InMemoryConsentRepository,
    InMemoryMemoryRepository,
    InMemoryProfileRepository,
)
from andes.memory.service import ConsentService, MemoryService, ProfileService
from andes.memory.store import MemoryStore


@pytest.fixture
def audit() -> InMemoryAuditLog:
    return InMemoryAuditLog()


@pytest.fixture
def consent_repo() -> InMemoryConsentRepository:
    return InMemoryConsentRepository()


@pytest.fixture
def profile_repo() -> InMemoryProfileRepository:
    return InMemoryProfileRepository()


@pytest.fixture
def memory_repo() -> InMemoryMemoryRepository:
    return InMemoryMemoryRepository()


@pytest.fixture
def consent_service(consent_repo, audit) -> ConsentService:
    return ConsentService(consent_repo, audit)


@pytest.fixture
def profile_service(profile_repo, audit) -> ProfileService:
    return ProfileService(profile_repo, audit)


@pytest.fixture
def memory_service(consent_service, profile_service, memory_repo, audit) -> MemoryService:
    return MemoryService(
        consent=consent_service,
        profile=profile_service,
        memory=memory_repo,
        audit=audit,
    )


@pytest.fixture
def memory_store(memory_repo) -> MemoryStore:
    return MemoryStore(memory_repo)


@pytest.fixture
def traveler_id() -> Iterator:
    yield uuid4()


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def retriever(embedder) -> Retriever:
    retriever = Retriever(embedder)
    retriever.ingest()
    return retriever


@pytest.fixture
def store() -> BookingStore:
    return BookingStore()


@pytest.fixture
def assistant(consent_service, profile_service, memory_store, retriever, store, audit) -> Assistant:
    return Assistant(
        consent=consent_service,
        profile=profile_service,
        memory=memory_store,
        retriever=retriever,
        audit=audit,
        store=store,
    )


@pytest.fixture
def events() -> InMemoryEventSink:
    return InMemoryEventSink()


@pytest.fixture
def conversation(assistant, consent_service, events) -> ConversationService:
    return ConversationService(
        assistant=assistant,
        consent=consent_service,
        events=events,
        auto_consent=True,
    )


@pytest.fixture
def grant_consents(consent_service):
    def _grant(traveler_id: UUID, *purposes: ConsentPurpose) -> None:
        for purpose in purposes or (
            ConsentPurpose.PERSONALIZATION,
            ConsentPurpose.QUOTATION,
            ConsentPurpose.BOOKING,
        ):
            consent_service.grant(traveler_id, purpose)

    return _grant
