"""Dependency wiring.

Builds the object graph for the running app (and for tests) from a single place.
Production swaps the in-memory repositories/store for Postgres-backed ones without
touching the domain code.
"""

from __future__ import annotations

from dataclasses import dataclass

from andes.agents.assistant import Assistant
from andes.analytics.events import EventSink, InMemoryEventSink
from andes.booking_api.store import BookingStore, get_store
from andes.conversation import ConversationService
from andes.core.config import get_settings
from andes.governance.audit import AuditLog, InMemoryAuditLog
from andes.knowledge.embeddings import get_embedder
from andes.knowledge.retriever import Retriever
from andes.memory.repository import (
    InMemoryConsentRepository,
    InMemoryMemoryRepository,
    InMemoryProfileRepository,
)
from andes.memory.service import ConsentService, ProfileService
from andes.memory.store import MemoryStore
from andes.observability.tracing import get_tracer


@dataclass
class Container:
    audit: AuditLog
    consent: ConsentService
    profile: ProfileService
    memory: MemoryStore
    retriever: Retriever
    store: BookingStore
    assistant: Assistant
    events: EventSink
    conversation: ConversationService


def build_container(
    *,
    store: BookingStore | None = None,
    auto_consent: bool | None = None,
) -> Container:
    settings = get_settings()
    audit = InMemoryAuditLog()
    consent = ConsentService(InMemoryConsentRepository(), audit)
    profile = ProfileService(InMemoryProfileRepository(), audit)
    memory = MemoryStore(InMemoryMemoryRepository(), get_embedder())
    retriever = Retriever(get_embedder())
    retriever.ingest()
    booking_store = store or get_store()

    assistant = Assistant(
        consent=consent,
        profile=profile,
        memory=memory,
        retriever=retriever,
        audit=audit,
        store=booking_store,
    )
    events = InMemoryEventSink()
    conversation = ConversationService(
        assistant=assistant,
        consent=consent,
        events=events,
        tracer=get_tracer(),
        auto_consent=auto_consent if auto_consent is not None else settings.app_env == "local",
    )
    return Container(
        audit=audit,
        consent=consent,
        profile=profile,
        memory=memory,
        retriever=retriever,
        store=booking_store,
        assistant=assistant,
        events=events,
        conversation=conversation,
    )
