#!/usr/bin/env python
"""Run ContextGraph context-quality benchmarks with HPS.

Usage:
  python -m src.scripts.run_context_quality_benchmark \
    --input docs/benchmarks/context-quality.codex-claude.jsonl \
    --output docs/benchmarks/context-quality-report.json \
    --markdown docs/benchmarks/context-quality-report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backend.perf.context_quality import benchmark_context_quality


def load_cases(input_path: Path) -> list[dict[str, Any]]:
    """Load benchmark cases from JSONL."""
    cases: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(case, dict):
                raise ValueError(f"line {line_number} must be a JSON object")
            cases.append(case)
    return cases


def render_markdown(report: dict[str, Any]) -> str:
    """Render a compact human-readable HPS report."""
    summary = report.get("summary", {})
    lines = [
        "# ContextGraph Context Quality Benchmark",
        "",
        f"Metric: `{report.get('metric')}`",
        f"Method: `{report.get('method')}`",
        "",
        "## Summary",
        "",
        f"- Cases: {summary.get('caseCount', 0)}",
        f"- Average baseline HPS: {summary.get('avgBaselineHps', 0)}",
        f"- Average CG HPS: {summary.get('avgCgHps', 0)}",
        f"- Average HPS reduction: {summary.get('avgHpsReductionPercent', 0)}%",
        f"- Average token reduction: {summary.get('avgTokenReductionPercent', 0)}%",
        "",
        "## Cases",
        "",
        "| Case | Project | Baseline Tokens | CG Tokens | Baseline HPS | CG HPS | HPS Reduction | Token Reduction |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    for item in report.get("cases", []):
        baseline = item["baseline"]
        cg = item["cg"]
        comparison = item["comparison"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("id", "")),
                    str(item.get("project", "")),
                    str(baseline["totalTokens"]),
                    str(cg["totalTokens"]),
                    str(baseline["hallucinationPressureScore"]),
                    str(cg["hallucinationPressureScore"]),
                    f"{comparison['hpsReductionPercent']}%",
                    f"{comparison['tokenReductionPercent']}%",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "HPS is a deterministic pre-answer context risk score. Lower is better.",
            "CG should reduce HPS while preserving gold evidence coverage.",
            "",
        ]
    )
    return "\n".join(lines)


def run_context_quality_benchmark(
    input_path: Path,
    output_path: Path,
    markdown_path: Path | None,
    repo_root: Path,
) -> dict[str, Any]:
    """Run the benchmark and write reports."""
    report = benchmark_context_quality(
        payload={"cases": load_cases(input_path)},
        repo_root=repo_root,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ContextGraph context-quality HPS benchmarks")
    parser.add_argument("--input", required=True, help="JSONL benchmark case manifest")
    parser.add_argument("--output", default="context-quality-report.json", help="JSON report path")
    parser.add_argument("--markdown", default="", help="Optional Markdown report path")
    parser.add_argument("--repo-root", default=".", help="Repo root for relative filePath chunks")
    args = parser.parse_args()

    report = run_context_quality_benchmark(
        input_path=Path(args.input),
        output_path=Path(args.output),
        markdown_path=Path(args.markdown) if args.markdown else None,
        repo_root=Path(args.repo_root).resolve(),
    )
    summary = report["summary"]
    print("\n=== ContextGraph Context Quality Benchmark ===\n")
    print(f"Cases: {summary['caseCount']}")
    print(f"Average baseline HPS: {summary['avgBaselineHps']}")
    print(f"Average CG HPS: {summary['avgCgHps']}")
    print(f"Average HPS reduction: {summary['avgHpsReductionPercent']}%")
    print(f"Average token reduction: {summary['avgTokenReductionPercent']}%")
    print(f"\nReport saved to: {args.output}")
    if args.markdown:
        print(f"Markdown saved to: {args.markdown}")


if __name__ == "__main__":
    main()