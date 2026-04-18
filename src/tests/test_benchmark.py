"""Tests for performance benchmarking framework."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.perf.benchmark import (
    BenchmarkResult,
    IncrementalBenchmarkResult,
    PerformanceBenchmark,
)


def test_benchmark_result_as_dict():
    result = BenchmarkResult(
        name="test",
        project_files=100,
        total_symbols=500,
        total_calls=1000,
        total_imports=200,
        duration_ms=5000,
        files_per_sec=20,
        symbols_per_sec=100,
        calls_per_sec=200,
        imports_per_sec=40,
    )
    d = result.as_dict()
    assert d["name"] == "test"
    assert d["project_files"] == 100
    assert d["duration_ms"] == 5000


def test_incremental_benchmark_result_as_dict():
    result = IncrementalBenchmarkResult(
        name="test",
        base_files=100,
        changed_files=5,
        base_symbols=500,
        new_symbols=10,
        base_calls=1000,
        new_calls=20,
        base_duration_ms=5000,
        incremental_duration_ms=500,
        improvement_factor=10.0,
    )
    d = result.as_dict()
    assert d["improvement_factor"] == 10.0


def test_benchmark_run_full_index():
    benchmark = PerformanceBenchmark()
    
    def mock_indexer(repo_path: str) -> dict:
        return {
            "files": 50,
            "symbols": 250,
            "calls": 500,
            "imports": 100,
        }
    
    result = benchmark.run_full_index_benchmark("test", "/tmp/repo", mock_indexer)
    assert result.project_files == 50
    assert result.total_symbols == 250
    assert result.total_calls == 500
    assert result.total_imports == 100
    assert result.error is None


def test_benchmark_run_full_index_error():
    benchmark = PerformanceBenchmark()
    
    def mock_indexer_error(repo_path: str) -> dict:
        raise RuntimeError("indexing failed")
    
    result = benchmark.run_full_index_benchmark("test", "/tmp/repo", mock_indexer_error)
    assert result.error is not None
    assert "indexing failed" in result.error


def test_benchmark_report_generation():
    benchmark = PerformanceBenchmark()
    
    def mock_indexer(repo_path: str) -> dict:
        return {
            "files": 50,
            "symbols": 250,
            "calls": 500,
            "imports": 100,
        }
    
    benchmark.run_full_index_benchmark("test1", "/tmp/repo1", mock_indexer)
    benchmark.run_full_index_benchmark("test2", "/tmp/repo2", mock_indexer)
    
    report = benchmark.report()
    assert "full_index_results" in report
    assert "summary" in report
    assert len(report["full_index_results"]) == 2
    assert report["summary"]["total_runs"] == 2


def test_benchmark_save_report(tmp_path):
    benchmark = PerformanceBenchmark()
    
    def mock_indexer(repo_path: str) -> dict:
        return {
            "files": 50,
            "symbols": 250,
            "calls": 500,
            "imports": 100,
        }
    
    benchmark.run_full_index_benchmark("test", "/tmp/repo", mock_indexer)
    
    report_path = tmp_path / "report.json"
    benchmark.save_report(str(report_path))
    
    assert report_path.exists()
    import json
    with open(report_path) as f:
        data = json.load(f)
    assert "full_index_results" in data
