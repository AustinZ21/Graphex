from pathlib import Path

import pytest

from backend.perf.token_efficiency import (
    TokenBenchmarkInputError,
    benchmark_token_efficiency,
    estimate_tokens,
)


def test_estimate_tokens_non_empty() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcdefgh") == 2


def test_benchmark_token_efficiency_with_text() -> None:
    payload = {
        "query": "demo",
        "baseline": {"text": "x" * 400},
        "cg": {"text": "x" * 40},
    }
    result = benchmark_token_efficiency(payload=payload, repo_root=Path("."))
    assert result["ok"] is True
    assert result["baselineTokens"] > result["cgTokens"]
    assert result["savedTokens"] > 0


def test_benchmark_token_efficiency_with_file_paths(tmp_path: Path) -> None:
    base_file = tmp_path / "baseline.txt"
    cg_file = tmp_path / "cg.txt"
    base_file.write_text("baseline " * 200, encoding="utf-8")
    cg_file.write_text("cg " * 20, encoding="utf-8")

    payload = {
        "baseline": {"filePaths": ["baseline.txt"]},
        "cg": {"filePaths": ["cg.txt"]},
    }
    result = benchmark_token_efficiency(payload=payload, repo_root=tmp_path)
    assert result["baseline"]["fileCount"] == 1
    assert result["cg"]["fileCount"] == 1
    assert result["savedPercent"] > 0


def test_benchmark_token_efficiency_requires_baseline_and_cg() -> None:
    with pytest.raises(TokenBenchmarkInputError):
        benchmark_token_efficiency(payload={"baseline": {"text": "a"}}, repo_root=Path("."))
