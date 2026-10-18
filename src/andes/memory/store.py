"""Long-term memory store with semantic recall."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import UUID

from andes.core.enums import MemoryKind
from andes.core.schemas import MemoryRecord
from andes.core.vector import cosine_similarity
from andes.memory.repository import MemoryRepository

Embedder = Callable[[str], list[float]]


class MemoryStore:
    """Stores long-term memory records and recalls them by similarity."""

    def __init__(self, repo: MemoryRepository, embedder: Embedder | None = None) -> None:
        self._repo = repo
        self._embedder = embedder

    def remember(
        self,
        traveler_id: UUID,
        content: str,
        kind: MemoryKind = MemoryKind.FACT,
        channel=None,
    ) -> MemoryRecord:
        embedding = self._embedder(content) if self._embedder else None
        record = MemoryRecord(
            traveler_id=traveler_id,
            kind=kind,
            content=content,
            channel=channel,
            embedding=embedding,
        )
        self._repo.add(record)
        return record

    def recent(self, traveler_id: UUID) -> list[MemoryRecord]:
        return sorted(self._repo.list(traveler_id), key=lambda r: r.ts, reverse=True)

    def search(self, traveler_id: UUID, query: str, k: int = 5) -> list[MemoryRecord]:
        if not self._embedder:
            raise RuntimeError("semantic search requires an embedder")
        query_vec = self._embedder(query)
        candidates = self._repo.list(traveler_id)
        scored: list[tuple[float, MemoryRecord]] = []
        for record in candidates:
            if record.embedding:
                scored.append((cosine_similarity(query_vec, record.embedding), record))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [record for _, record in scored[:k]]

    @staticmethod
    def highlights(records: Sequence[MemoryRecord], limit: int = 5) -> list[str]:
        return [r.content for r in records[:limit]]
