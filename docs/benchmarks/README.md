# Context Quality Benchmarks

This directory contains deterministic ContextGraph context-quality benchmarks.

The benchmark compares baseline broad context against CG-reduced context for the same task. It reports token counts, useless tokens, gold evidence coverage, ambiguity, redundancy, and Hallucination Pressure Score (HPS).

Run the sample CodexCLI and ClaudeCLI benchmark:

```powershell
python -m src.scripts.run_context_quality_benchmark `
  --input docs/benchmarks/context-quality.codex-claude.jsonl `
  --output docs/benchmarks/context-quality-report.json `
  --markdown docs/benchmarks/context-quality-report.md
```

HPS is a pre-answer context risk score. Lower is better. It is deterministic and does not require an LLM call.

```text
HPS = 100 * (
    0.45 * missing_evidence_risk
  + 0.35 * noise_risk
  + 0.10 * redundancy_risk
  + 0.10 * ambiguity_risk
)
```

The benchmark should improve HPS by reducing noisy context while preserving gold evidence coverage.