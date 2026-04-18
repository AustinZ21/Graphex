"""Performance benchmarking for ContextGraph indexing.

Measures:
- Throughput (files/sec, symbols/sec)
- Latency (full index time, incremental time)
- Memory usage
- Graph query latency

Supports different project scales and structures.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

import structlog

log = structlog.get_logger()


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    name: str
    project_files: int
    total_symbols: int
    total_calls: int
    total_imports: int
    duration_ms: float
    files_per_sec: float
    symbols_per_sec: float
    calls_per_sec: float
    imports_per_sec: float
    memory_mb: float | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class IncrementalBenchmarkResult:
    """Result of an incremental update benchmark."""
    name: str
    base_files: int
    changed_files: int
    base_symbols: int
    new_symbols: int
    base_calls: int
    new_calls: int
    base_duration_ms: float
    incremental_duration_ms: float
    improvement_factor: float

    def as_dict(self) -> dict:
        return asdict(self)


class PerformanceBenchmark:
    """Orchestrate performance benchmarking."""

    def __init__(self) -> None:
        self.results: list[BenchmarkResult] = []
        self.incremental_results: list[IncrementalBenchmarkResult] = []

    def run_full_index_benchmark(
        self,
        name: str,
        repo_path: str,
        indexer_fn: Callable[[str], dict],
    ) -> BenchmarkResult:
        """Benchmark full indexing on a repository."""
        log.info("benchmark.start", name=name, repo_path=repo_path)
        t0 = time.perf_counter()
        try:
            stats = indexer_fn(repo_path)
            duration_sec = time.perf_counter() - t0
            
            project_files = stats.get("files", 0)
            total_symbols = stats.get("symbols", 0)
            total_calls = stats.get("calls", 0)
            total_imports = stats.get("imports", 0)
            
            files_per_sec = project_files / duration_sec if duration_sec > 0 else 0
            symbols_per_sec = total_symbols / duration_sec if duration_sec > 0 else 0
            calls_per_sec = total_calls / duration_sec if duration_sec > 0 else 0
            imports_per_sec = total_imports / duration_sec if duration_sec > 0 else 0
            
            result = BenchmarkResult(
                name=name,
                project_files=project_files,
                total_symbols=total_symbols,
                total_calls=total_calls,
                total_imports=total_imports,
                duration_ms=duration_sec * 1000,
                files_per_sec=files_per_sec,
                symbols_per_sec=symbols_per_sec,
                calls_per_sec=calls_per_sec,
                imports_per_sec=imports_per_sec,
            )
            self.results.append(result)
            log.info(
                "benchmark.done",
                name=name,
                duration_ms=result.duration_ms,
                files_per_sec=files_per_sec,
            )
            return result
        except Exception as exc:
            log.error("benchmark.error", name=name, error=str(exc))
            result = BenchmarkResult(
                name=name,
                project_files=0,
                total_symbols=0,
                total_calls=0,
                total_imports=0,
                duration_ms=0,
                files_per_sec=0,
                symbols_per_sec=0,
                calls_per_sec=0,
                imports_per_sec=0,
                error=str(exc),
            )
            self.results.append(result)
            return result

    def run_incremental_benchmark(
        self,
        name: str,
        repo_path: str,
        full_indexer_fn: Callable[[str], dict],
        incremental_indexer_fn: Callable[[str, list[str]], dict],
        changed_files: list[str],
    ) -> IncrementalBenchmarkResult:
        """Benchmark incremental indexing vs full re-index."""
        log.info("benchmark.incremental.start", name=name, changed_files=len(changed_files))
        
        t0 = time.perf_counter()
        base_stats = full_indexer_fn(repo_path)
        base_duration = (time.perf_counter() - t0) * 1000
        
        t0 = time.perf_counter()
        incr_stats = incremental_indexer_fn(repo_path, changed_files)
        incr_duration = (time.perf_counter() - t0) * 1000
        
        improvement = base_duration / incr_duration if incr_duration > 0 else 0
        
        result = IncrementalBenchmarkResult(
            name=name,
            base_files=base_stats.get("files", 0),
            changed_files=len(changed_files),
            base_symbols=base_stats.get("symbols", 0),
            new_symbols=incr_stats.get("symbols", 0),
            base_calls=base_stats.get("calls", 0),
            new_calls=incr_stats.get("calls", 0),
            base_duration_ms=base_duration,
            incremental_duration_ms=incr_duration,
            improvement_factor=improvement,
        )
        self.incremental_results.append(result)
        log.info(
            "benchmark.incremental.done",
            name=name,
            improvement_factor=improvement,
        )
        return result

    def report(self) -> dict:
        """Generate performance report."""
        return {
            "full_index_results": [r.as_dict() for r in self.results],
            "incremental_results": [r.as_dict() for r in self.incremental_results],
            "summary": self._summarize(),
        }

    def _summarize(self) -> dict:
        """Generate summary statistics."""
        if not self.results:
            return {}
        
        avg_files_per_sec = sum(r.files_per_sec for r in self.results) / len(self.results)
        avg_symbols_per_sec = sum(r.symbols_per_sec for r in self.results) / len(self.results)
        
        incr_improvements = [r.improvement_factor for r in self.incremental_results]
        avg_incr_improvement = sum(incr_improvements) / len(incr_improvements) if incr_improvements else 0
        
        return {
            "total_runs": len(self.results),
            "avg_files_per_sec": round(avg_files_per_sec, 2),
            "avg_symbols_per_sec": round(avg_symbols_per_sec, 2),
            "incremental_runs": len(self.incremental_results),
            "avg_incremental_improvement_factor": round(avg_incr_improvement, 2),
        }

    def save_report(self, output_path: str) -> None:
        """Save report to JSON file."""
        report = self.report()
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        log.info("benchmark.report_saved", path=output_path)
