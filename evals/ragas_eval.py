"""RAG evaluation.

Offline (default): measures retrieval quality with ``top_k_accuracy`` using the
deterministic ``FakeEmbedder`` so it runs in CI with no model/network.

With ``ANDES_EMBEDDER=bge-m3`` it uses the local multilingual model. If ``ragas``
is installed and an LLM is reachable, it additionally computes response-level
metrics; otherwise it reports that the RAGAS stage was skipped.

    uv run python evals/ragas_eval.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from andes.knowledge.embeddings import FakeEmbedder, get_embedder
from andes.knowledge.retriever import Retriever, top_k_accuracy

DATASET = Path(__file__).with_name("dataset.jsonl")
K = 3


def load_cases() -> list[tuple[str, str]]:
    cases: list[tuple[str, str]] = []
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        cases.append((row["query"], row["expected_destination"]))
    return cases


def build_retriever() -> Retriever:
    embedder = get_embedder() if os.environ.get("ANDES_EMBEDDER") == "bge-m3" else FakeEmbedder()
    retriever = Retriever(embedder)
    retriever.ingest()
    return retriever


def retrieve_hits(retriever: Retriever, cases: list[tuple[str, str]]) -> list[dict]:
    rows: list[dict] = []
    for query, expected in cases:
        contexts = [s.description for s in retriever.query(query, k=K)]
        rows.append(
            {
                "question": query,
                "contexts": contexts,
                "answer": f"Recomiendo {contexts[0][:40]}" if contexts else "",
                "ground_truth": expected,
            }
        )
    return rows


def run_ragas(rows: list[dict]) -> None:
    try:
        from datasets import Dataset  # noqa: PLC0415
        from ragas import evaluate  # noqa: PLC0415
        from ragas.metrics import answer_relevancy, faithfulness  # noqa: PLC0415
    except Exception:
        print("RAGAS stage skipped (ragas/datasets not installed)")
        return
    result = evaluate(Dataset.from_list(rows), metrics=[faithfulness, answer_relevancy])
    print("RAGAS:", result)


def main() -> None:
    cases = load_cases()
    retriever = build_retriever()
    accuracy = top_k_accuracy(cases, retriever, k=K)
    print(f"retrieval top-{K} accuracy: {accuracy:.2%} ({len(cases)} cases)")
    assert accuracy >= 0.75, f"retrieval accuracy too low: {accuracy:.2%}"
    run_ragas(retrieve_hits(retriever, cases))


if __name__ == "__main__":
    main()
