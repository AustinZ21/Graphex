# ContextGraph Context Quality Benchmark

Metric: `hallucination-pressure-score`
Method: `hps-context-quality-v1`

## Summary

- Cases: 2
- Average baseline HPS: 60.84
- Average CG HPS: 14.12
- Average HPS reduction: 77.11%
- Average token reduction: 35.4%

## Cases

| Case | Project | Baseline Tokens | CG Tokens | Baseline HPS | CG HPS | HPS Reduction | Token Reduction |
|---|---|---:|---:|---:|---:|---:|---:|
| claudecli-mcp-timeout | ClaudeCLI | 193 | 82 | 66.08 | 17.5 | 73.52% | 57.51% |
| codexcli-mcp-mutation-owner | CodexCLI | 143 | 124 | 55.6 | 10.73 | 80.7% | 13.29% |

## Interpretation

HPS is a deterministic pre-answer context risk score. Lower is better.
CG should reduce HPS while preserving gold evidence coverage.
