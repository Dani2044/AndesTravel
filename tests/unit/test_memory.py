from __future__ import annotations

import pytest

from andes.core.enums import ConsentPurpose, MemoryKind
from andes.core.errors import ConsentRequired
from andes.memory.store import MemoryStore


def test_consent_grant_and_check(consent_service, traveler_id):
    assert not consent_service.is_granted(traveler_id, ConsentPurpose.QUOTATION)
    consent_service.grant(traveler_id, ConsentPurpose.QUOTATION, {"channel": "web"})
    assert consent_service.is_granted(traveler_id, ConsentPurpose.QUOTATION)


def test_consent_revoke(consent_service, traveler_id):
    consent_service.grant(traveler_id, ConsentPurpose.BOOKING)
    consent_service.revoke(traveler_id, ConsentPurpose.BOOKING)
    assert not consent_service.is_granted(traveler_id, ConsentPurpose.BOOKING)
    assert len(consent_service.history(traveler_id)) == 2


def test_consent_require_raises(consent_service, traveler_id):
    with pytest.raises(ConsentRequired):
        consent_service.require(traveler_id, ConsentPurpose.PERSONALIZATION)


def test_consent_grant_is_audited(consent_service, audit, traveler_id):
    consent_service.grant(traveler_id, ConsentPurpose.BOOKING, {"version": "v2"})
    actions = [e.action for e in audit.entries()]
    assert "consent.grant" in actions


def test_profile_merge(profile_service, traveler_id):
    profile_service.update(traveler_id, {"destination": "Eje Cafetero", "party": 4})
    profile_service.update(traveler_id, {"party": 5, "budget": 6_000_000})
    profile = profile_service.get(traveler_id)
    assert profile is not None
    assert profile.attributes == {
        "destination": "Eje Cafetero",
        "party": 5,
        "budget": 6_000_000,
    }


def test_memory_remember_and_recent(memory_store, traveler_id):
    memory_store.remember(traveler_id, "viaja en diciembre", MemoryKind.PREFERENCE)
    memory_store.remember(traveler_id, "presupuesto 6M COP", MemoryKind.FACT)
    recent = memory_store.recent(traveler_id)
    assert len(recent) == 2


def test_memory_semantic_search(memory_repo, traveler_id):
    def embedder(text: str) -> list[float]:
        # trivial bag-of-words embedding
        vocab = ["playa", "montaña", "familia", "aventura"]
        return [float(text.lower().count(w)) for w in vocab]

    store = MemoryStore(memory_repo, embedder=embedder)
    store.remember(traveler_id, "le gusta la playa en familia", MemoryKind.PREFERENCE)
    store.remember(traveler_id, "quiere montaña y aventura", MemoryKind.PREFERENCE)
    results = store.search(traveler_id, "playa familia", k=1)
    assert "playa" in results[0].content


def test_memory_search_requires_embedder(memory_store, traveler_id):
    with pytest.raises(RuntimeError):
        memory_store.search(traveler_id, "x")


def test_arco_erasure(memory_service, profile_service, traveler_id):
    profile_service.update(traveler_id, {"destination": "Cartagena"})
    memory_service.consent.grant(traveler_id, ConsentPurpose.PERSONALIZATION)
    memory_service.erase(traveler_id)
    assert profile_service.get(traveler_id) is None
