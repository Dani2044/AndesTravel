"""A tiny in-memory vector index.

Production uses pgvector via SQLAlchemy (see ``andes.persistence``); this index
keeps the retriever testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from andes.core.vector import cosine_similarity


@dataclass
class IndexEntry:
    id: str
    embedding: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


class VectorIndex:
    def __init__(self) -> None:
        self._entries: list[IndexEntry] = []

    def add(self, id: str, embedding: list[float], payload: dict[str, Any]) -> None:
        self._entries.append(IndexEntry(id=id, embedding=embedding, payload=payload))

    def search(self, query: list[float], k: int = 3) -> list[tuple[float, IndexEntry]]:
        scored = [(cosine_similarity(query, entry.embedding), entry) for entry in self._entries]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:k]

    def __len__(self) -> int:
        return len(self._entries)
