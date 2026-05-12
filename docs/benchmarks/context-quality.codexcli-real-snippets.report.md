# ContextGraph Context Quality Benchmark

Metric: `hallucination-pressure-score`
Method: `hps-context-quality-v1`

## Summary

- Cases: 33
- Average baseline HPS: 56.96
- Average CG HPS: 5.73
- Average HPS reduction: 89.88%
- Average token reduction: 78.2%

## Cases

| Case | Project | Baseline Tokens | CG Tokens | Baseline HPS | CG HPS | HPS Reduction | Token Reduction |
|---|---|---:|---:|---:|---:|---:|---:|
| codexcli-real-config-mcp-edit | CodexCLI | 5064 | 2516 | 59.85 | 6.48 | 89.17% | 50.32% |
| codexcli-real-config-types | CodexCLI | 5020 | 2497 | 60.12 | 4.21 | 93.0% | 50.26% |
| codexcli-real-config-merge | CodexCLI | 4970 | 1297 | 60.43 | 12.58 | 79.18% | 73.9% |
| codexcli-real-core-apply-patch | CodexCLI | 4581 | 1681 | 63.08 | 11.2 | 82.24% | 63.3% |
| codexcli-real-core-agents-md | CodexCLI | 8669 | 3283 | 47.09 | 5.74 | 87.81% | 62.13% |
| codexcli-real-core-client-common | CodexCLI | 6166 | 3010 | 54.36 | 6.26 | 88.48% | 51.18% |
| codexcli-real-core-config-schema | CodexCLI | 13626 | 1258 | 62.22 | 12.66 | 79.65% | 90.77% |
| codexcli-real-core-config-permissions | CodexCLI | 16338 | 3279 | 56.74 | 3.94 | 93.06% | 79.93% |
| codexcli-real-core-config-edit | CodexCLI | 23414 | 2903 | 48.41 | 0.57 | 98.82% | 87.6% |
| codexcli-real-core-environment-context | CodexCLI | 6556 | 3026 | 52.86 | 6.22 | 88.23% | 53.84% |
| codexcli-real-handler-apply-patch | CodexCLI | 7675 | 3203 | 53.76 | 6.06 | 88.73% | 58.27% |
| codexcli-real-handler-shell | CodexCLI | 12822 | 3245 | 56.95 | 3.55 | 93.77% | 74.69% |
| codexcli-real-handler-unified-exec | CodexCLI | 10504 | 2540 | 52.86 | 6.32 | 88.04% | 75.82% |
| codexcli-real-exec-cli | CodexCLI | 28165 | 2438 | 63.5 | 7.62 | 88.0% | 91.34% |
| codexcli-real-exec-lib | CodexCLI | 32297 | 3446 | 59.11 | 4.79 | 91.9% | 89.33% |
| codexcli-real-app-server-transport | CodexCLI | 36325 | 3005 | 59.76 | 3.11 | 94.8% | 91.73% |
| codexcli-real-app-server-config-manager-service | CodexCLI | 38189 | 2954 | 58.26 | 4.95 | 91.5% | 92.26% |
| codexcli-real-protocol-common | CodexCLI | 6740 | 2097 | 62.39 | 1.19 | 98.09% | 68.89% |
| codexcli-real-protocol-v2 | CodexCLI | 33828 | 1877 | 35.79 | 7.31 | 79.58% | 94.45% |
| codexcli-real-mcp-connection-manager | CodexCLI | 14550 | 3192 | 44.56 | 4.18 | 90.62% | 78.06% |
| codexcli-real-core-skills-loader | CodexCLI | 28202 | 2833 | 47.33 | 4.3 | 90.91% | 89.95% |
| codexcli-real-core-skills-manager | CodexCLI | 29594 | 3037 | 56.2 | 4.26 | 92.42% | 89.74% |
| codexcli-real-core-plugins-store | CodexCLI | 9649 | 3274 | 54.58 | 6.24 | 88.57% | 66.07% |
| codexcli-real-core-plugins-loader | CodexCLI | 14960 | 2782 | 58.23 | 4.26 | 92.68% | 81.4% |
| codexcli-real-hooks-output-spill | CodexCLI | 7421 | 1564 | 62.71 | 6.78 | 89.19% | 78.92% |
| codexcli-real-models-manager-manager | CodexCLI | 32056 | 3321 | 57.09 | 5.97 | 89.54% | 89.64% |
| codexcli-real-memories-storage | CodexCLI | 8615 | 3331 | 58.79 | 5.39 | 90.83% | 61.33% |
| codexcli-real-memories-guard | CodexCLI | 7827 | 1399 | 61.77 | 8.11 | 86.87% | 82.13% |
| codexcli-real-rollout-session-index | CodexCLI | 87939 | 3061 | 63.12 | 3.65 | 94.22% | 96.52% |
| codexcli-real-rollout-recorder | CodexCLI | 96127 | 2886 | 60.23 | 3.93 | 93.48% | 97.0% |
| codexcli-real-analytics-client | CodexCLI | 27596 | 3234 | 61.6 | 4.64 | 92.47% | 88.28% |
| codexcli-real-api-bridge | CodexCLI | 27367 | 3475 | 61.87 | 4.39 | 92.9% | 87.3% |
| codexcli-real-chatgpt-workspace-settings | CodexCLI | 25668 | 1515 | 64.04 | 8.18 | 87.23% | 94.1% |

## Interpretation

HPS is a deterministic pre-answer context risk score. Lower is better.
CG should reduce HPS while preserving gold evidence coverage.
