"""Tests for P@5 evaluation runner."""

from unittest.mock import MagicMock

from backend.eval.dataset import EvalCase
from backend.eval.runner import EvalRunner


def _mock_graph(rows: list):
    """Return a GraphClient mock whose .query() returns the given rows."""
    result = MagicMock()
    result.result_set = rows
    graph = MagicMock()
    graph.query.return_value = result
    return graph


def test_perfect_score():
    graph = _mock_graph([["backend.indexer.hasher.sha256_file", "function", "hasher.py", 1, 10]])
    dataset = [
        EvalCase(
            query="sha256 hash",
            expected_qnames=["backend.indexer.hasher.sha256_file"],
            top_k=5,
        )
    ]
    runner = EvalRunner(graph, dataset=dataset)
    report = runner.run()
    assert report.macro_p_at_5 == 1.0


def test_zero_score_on_miss():
    graph = _mock_graph([["some.other.Symbol", "function", "other.py", 1, 5]])
    dataset = [
        EvalCase(
            query="SHA256 hash",
            expected_qnames=["backend.indexer.hasher.sha256_file"],
            top_k=5,
        )
    ]
    runner = EvalRunner(graph, dataset=dataset)
    report = runner.run()
    assert report.macro_p_at_5 == 0.0


def test_latency_recorded():
    graph = _mock_graph([])
    dataset = [EvalCase(query="q", expected_qnames=["a.b"], top_k=5)]
    runner = EvalRunner(graph, dataset=dataset)
    report = runner.run()
    assert report.p50_latency_ms >= 0


def test_report_as_dict_keys():
    graph = _mock_graph([])
    runner = EvalRunner(graph, dataset=[])
    report = runner.run()
    d = report.as_dict()
    assert "macro_p_at_5" in d
    assert "p95_latency_ms" in d
    assert "cases" in d


def test_percentile_edge_cases():
    from backend.eval.runner import EvalRunner as _R
    assert _R._percentile([], 50) == 0.0
    assert _R._percentile([10.0], 99) == 10.0
    assert _R._percentile([5.0, 15.0], 50) == 5.0
