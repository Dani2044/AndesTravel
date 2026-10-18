from __future__ import annotations

import pytest

from andes.knowledge.embeddings import FakeEmbedder
from andes.knowledge.retriever import Retriever, top_k_accuracy
from andes.knowledge.vector_index import VectorIndex


def test_fake_embedder_is_deterministic():
    embed = FakeEmbedder(dim=64)
    assert embed("playa familia") == embed("playa familia")
    assert len(embed("playa")) == 64


def test_vector_index_ranks_by_similarity():
    embed = FakeEmbedder()
    index = VectorIndex()
    index.add("a", embed("playa mar caribe"), {"destination": "Cartagena"})
    index.add("b", embed("montaña café finca"), {"destination": "Eje Cafetero"})
    results = index.search(embed("playa y mar"), k=1)
    assert results[0][1].payload["destination"] == "Cartagena"


def test_retriever_query_returns_summaries(retriever):
    summaries = retriever.query("playa buceo arrecifes", k=2)
    assert summaries
    assert all(0.0 <= s.score <= 1.0000001 for s in summaries)
    assert summaries[0].destination in {"San Andrés", "Tayrona", "Cartagena"}


def test_retriever_recommend_uses_profile(retriever):
    summaries = retriever.recommend({"destination": "Amazonía", "tags": ["ecoturismo"]}, k=1)
    assert summaries[0].destination == "Amazonía"


def test_retriever_raises_before_ingest():
    retriever = Retriever(FakeEmbedder())
    with pytest.raises(RuntimeError):
        retriever.query("playa")


def test_top_k_accuracy_hits_and_misses(retriever):
    cases = [
        ("playa buceo arrecife de coral", "San Andrés"),
        ("fin cas cafetera montaña", "Eje Cafetero"),
        ("selva amazónica comunidades", "Amazonía"),
    ]
    accuracy = top_k_accuracy(cases, retriever, k=3)
    assert accuracy == 1.0


def test_top_k_accuracy_empty_is_perfect(retriever):
    assert top_k_accuracy([], retriever) == 1.0
