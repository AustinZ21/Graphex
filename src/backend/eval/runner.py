"""Evaluation runner – P@5 precision and latency benchmarks.

Usage (CLI):
    python -m backend.eval.runner --repo-path /path/to/repo

Usage (programmatic / MCP):
    from backend.eval.runner import EvalRunner
    report = await EvalRunner(graph).run()

Metrics:
- P@5  : fraction of top-5 retrieved symbols that appear in the expected set.
- Latency P50 / P95 / P99 in milliseconds across all benchmark queries.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Sequence

import structlog

from backend.eval.dataset import QUERIES, EvalCase
from backend.graph.client import GraphClient
from backend.graph import schema as S

log = structlog.get_logger()


@dataclass
class CaseResult:
    query: str
    hits: int
    expected: int
    precision_at_k: float
    latency_ms: float


@dataclass
class EvalReport:
    macro_p_at_5: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    cases: list[CaseResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "macro_p_at_5": round(self.macro_p_at_5, 4),
            "p50_latency_ms": round(self.p50_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "cases": [
                {
                    "query": c.query,
                    "precision_at_k": round(c.precision_at_k, 4),
                    "hits": c.hits,
                    "expected": c.expected,
                    "latency_ms": round(c.latency_ms, 2),
                }
                for c in self.cases
            ],
        }


class EvalRunner:
    """Run the evaluation benchmark against a live graph."""

    def __init__(self, graph: GraphClient, dataset: list[EvalCase] | None = None) -> None:
        self._graph = graph
        self._dataset = dataset or QUERIES

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> EvalReport:
        case_results: list[CaseResult] = []
        latencies: list[float] = []

        for case in self._dataset:
            result = self._eval_case(case)
            case_results.append(result)
            latencies.append(result.latency_ms)

        macro_p = (
            sum(c.precision_at_k for c in case_results) / len(case_results)
            if case_results
            else 0.0
        )
        latencies_sorted = sorted(latencies)

        report = EvalReport(
            macro_p_at_5=macro_p,
            p50_latency_ms=self._percentile(latencies_sorted, 50),
            p95_latency_ms=self._percentile(latencies_sorted, 95),
            p99_latency_ms=self._percentile(latencies_sorted, 99),
            cases=case_results,
        )
        log.info(
            "eval.done",
            macro_p_at_5=round(macro_p, 4),
            p50_ms=round(report.p50_latency_ms, 2),
            p95_ms=round(report.p95_latency_ms, 2),
        )
        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _eval_case(self, case: EvalCase) -> CaseResult:
        t0 = time.perf_counter()
        retrieved = self._retrieve(case.query, case.top_k)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        expected_set = set(case.expected_qnames)
        hits = sum(1 for qname in retrieved if qname in expected_set)
        precision = hits / min(case.top_k, max(1, len(expected_set)))

        return CaseResult(
            query=case.query,
            hits=hits,
            expected=len(expected_set),
            precision_at_k=precision,
            latency_ms=latency_ms,
        )

    def _retrieve(self, query: str, limit: int) -> list[str]:
        """Retrieve top-*limit* symbol qualified names for *query*."""
        try:
            result = self._graph.query(
                S.QUERY_FIND_SYMBOL,
                {"name": query, "limit": limit},
            )
            rows = result.result_set
            if rows:
                return [row[0] for row in rows if row]
        except Exception:
            pass

        # Fallback: context-style CONTAINS match
        try:
            result = self._graph.query(
                S.QUERY_RETRIEVE_CONTEXT,
                {"query": query, "limit": limit},
            )
            rows = result.result_set
            return [row[0] for row in rows if row]
        except Exception:
            return []

    @staticmethod
    def _percentile(sorted_values: list[float], pct: int) -> float:
        if not sorted_values:
            return 0.0
        idx = max(0, int(len(sorted_values) * pct / 100) - 1)
        return sorted_values[idx]


# ------------------------------------------------------------------
# CLI entrypoint
# ------------------------------------------------------------------

def _cli() -> None:
    import argparse, json, asyncio

    parser = argparse.ArgumentParser(description="Run ContextGraph eval benchmark")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6379)
    args = parser.parse_args()

    graph = GraphClient(host=args.host, port=args.port)
    graph.connect()
    runner = EvalRunner(graph)
    report = runner.run()
    print(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    _cli()
