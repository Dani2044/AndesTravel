"""Catalog retrieval over a vector index."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from andes.core.schemas import PackageSummary
from andes.core.seed import CATALOG, SeedPackage
from andes.knowledge.embeddings import Embedder
from andes.knowledge.vector_index import VectorIndex


def _document(package: SeedPackage) -> str:
    return (
        f"{package['destination']} {package['name']}. {package['description']} "
        f"Etiquetas: {', '.join(package['tags'])}."
    )


def _query_from_profile(profile: dict) -> str:
    parts: list[str] = []
    if destination := profile.get("destination"):
        parts.append(str(destination))
    if tags := profile.get("tags"):
        parts.extend(str(t) for t in tags)
    if party := profile.get("party"):
        parts.append(f"grupo de {party} viajeros")
    if preferences := profile.get("preferences"):
        parts.append(str(preferences))
    return " ".join(parts)


class Retriever:
    """Embeds the catalog and answers profile-based queries."""

    def __init__(self, embedder: Embedder, index: VectorIndex | None = None) -> None:
        self._embedder = embedder
        self._index = index or VectorIndex()

    @property
    def index(self) -> VectorIndex:
        return self._index

    def ingest(self, packages: Sequence[SeedPackage] = CATALOG) -> None:
        self._index = VectorIndex()
        for package in packages:
            embedding = self._embedder(_document(package))
            self._index.add(package["id"], embedding, dict(package))

    def query(self, text: str, k: int = 3) -> list[PackageSummary]:
        if len(self._index) == 0:
            raise RuntimeError("index is empty; call ingest() first")
        results = self._index.search(self._embedder(text), k=k)
        summaries: list[PackageSummary] = []
        for score, entry in results:
            payload = entry.payload
            summaries.append(
                PackageSummary(
                    id=UUID(payload["id"]),
                    destination=payload["destination"],
                    name=payload["name"],
                    description=payload["description"],
                    duration_days=payload["duration_days"],
                    tags=list(payload["tags"]),
                    score=round(score, 6),
                )
            )
        return summaries

    def recommend(self, profile: dict, k: int = 3) -> list[PackageSummary]:
        return self.query(_query_from_profile(profile), k=k)


def top_k_accuracy(cases: Sequence[tuple[str, str]], retriever: Retriever, k: int = 3) -> float:
    """Fraction of cases whose expected destination appears in the top-k results.

    ``cases`` is a sequence of ``(query_text, expected_destination)``.
    """

    if not cases:
        return 1.0
    hits = 0
    for query, expected in cases:
        destinations = {s.destination for s in retriever.query(query, k=k)}
        if expected in destinations:
            hits += 1
    return hits / len(cases)
