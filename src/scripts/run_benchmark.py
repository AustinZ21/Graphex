#!/usr/bin/env python
"""Performance benchmark runner for ContextGraph.

Usage:
  python -m src.scripts.run_benchmark [--repo REPO_PATH] [--output REPORT_PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import structlog

from backend.graph.client import GraphClient
from backend.indexer.pipeline import IndexPipeline
from backend.perf.benchmark import PerformanceBenchmark

log = structlog.get_logger()


def run_benchmarks(repo_path: str, output_path: str = "benchmark_report.json") -> None:
    """Run comprehensive performance benchmarks."""
    log.info("benchmark.runner.start", repo_path=repo_path)
    
    graph = GraphClient()
    pipeline = IndexPipeline(graph)
    benchmark = PerformanceBenchmark()
    
    try:
        result = benchmark.run_full_index_benchmark(
            name="full_index",
            repo_path=repo_path,
            indexer_fn=lambda rp: pipeline.index_full(rp),
        )
        
        log.info(
            "full_index_result",
            files=result.project_files,
            symbols=result.total_symbols,
            calls=result.total_calls,
            imports=result.total_imports,
            duration_ms=result.duration_ms,
            files_per_sec=result.files_per_sec,
        )
        
        benchmark.save_report(output_path)
        log.info("benchmark.runner.done", report_path=output_path)
        
        report = benchmark.report()
        print("\n=== ContextGraph Performance Benchmark ===\n")
        print(f"Repository: {repo_path}")
        print(f"Files indexed: {result.project_files}")
        print(f"Total symbols: {result.total_symbols}")
        print(f"Total calls: {result.total_calls}")
        print(f"Total imports: {result.total_imports}")
        print(f"Duration: {result.duration_ms:.2f} ms")
        print(f"Throughput: {result.files_per_sec:.2f} files/sec")
        print(f"Symbol indexing: {result.symbols_per_sec:.2f} symbols/sec")
        print(f"Call indexing: {result.calls_per_sec:.2f} calls/sec")
        print(f"Import indexing: {result.imports_per_sec:.2f} imports/sec")
        print(f"\nReport saved to: {output_path}\n")
        
    except Exception as exc:
        log.error("benchmark.runner.error", error=str(exc))
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ContextGraph performance benchmarks")
    parser.add_argument(
        "--repo",
        default=".",
        help="Repository path to benchmark (default: current directory)",
    )
    parser.add_argument(
        "--output",
        default="benchmark_report.json",
        help="Output report path (default: benchmark_report.json)",
    )
    
    args = parser.parse_args()
    run_benchmarks(args.repo, args.output)


if __name__ == "__main__":
    main()
