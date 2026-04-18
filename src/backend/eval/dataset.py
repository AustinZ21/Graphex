"""Curated evaluation dataset for P@5 benchmarking.

Each entry in QUERIES maps a natural-language or symbol-name query to the
set of qualified symbol names that a correct retrieval should return within
the top-5 results.

For Phase 2 the dataset is seeded with fixtures that exercise the
ContextGraph codebase itself so that CI can validate retrieval quality
as the index evolves.

To extend: add entries to QUERIES and ensure the corresponding symbols
exist after a full index of this repository.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalCase:
    query: str
    expected_qnames: list[str]   # ordered by relevance; first = most relevant
    top_k: int = 5


# ------------------------------------------------------------------
# Seed dataset (auto-validated when the repo is self-indexed)
# ------------------------------------------------------------------

QUERIES: list[EvalCase] = [
    EvalCase(
        query="IndexPipeline",
        expected_qnames=["backend.indexer.pipeline.IndexPipeline"],
    ),
    EvalCase(
        query="find symbol by name",
        expected_qnames=[
            "backend.tools.server.find_symbol",
            "backend.graph.client.GraphClient.query",
        ],
    ),
    EvalCase(
        query="GraphClient connect",
        expected_qnames=["backend.graph.client.GraphClient.connect"],
    ),
    EvalCase(
        query="Redis Streams job producer",
        expected_qnames=[
            "backend.queue.streams.JobProducer.publish",
            "backend.tools.producer.MCPProducer.submit_full_index",
        ],
    ),
    EvalCase(
        query="SHA256 file hash",
        expected_qnames=["backend.indexer.hasher.sha256_file"],
    ),
]
