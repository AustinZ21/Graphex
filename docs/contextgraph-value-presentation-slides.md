---
marp: true
theme: default
paginate: true
title: "ContextGraph + AST: Reliable and Efficient AI Coding"
description: "How structure-first context and AST controls reduce hallucination, improve quality, and lower cost."
---

# ContextGraph + AST
## Make AI Coding Reliable, Fast, and Cost-Efficient

Presenter: Your Name
Date: 2026-05-11

---

# 1. Why This Matters

- AI output quality is now an engineering and business KPI.
- Teams need lower hallucination, higher delivery confidence, and lower token cost.
- ContextGraph solves context selection.
- AST solves output correctness and structural control.

---

# 2. Core Problem

## Most failures come from two gaps

- Gap A: weak retrieval context (wrong files, missing dependencies).
- Gap B: unconstrained code generation (invalid syntax, fake APIs, wrong references).
- Consequence: hallucinations, rework, and slow delivery.

---

# 3. Solution Overview

## Structure-first AI coding

- ContextGraph: graph-grounded evidence retrieval.
- AST: syntax and semantic guardrails for generated code.
- Combined effect: fewer hallucinations, better quality, lower token usage, faster iteration.

---

# 4. ContextGraph Role

## Retrieve the right evidence before generation

- Models query repository relationships, not only keywords.
- Retrieval flow: impact graph -> optimized context -> minimal code.
- Better file/symbol targeting and dependency awareness.

---

# 5. AST Role

## Turn generated text into enforceable structure

- Parse model output into Abstract Syntax Tree (AST) immediately.
- Reject invalid syntax at parse time.
- Validate symbols and API usage against allowed schema and codebase contracts.
- Support constrained generation by limiting allowed AST node patterns.

---

# 6. Hallucination Mitigation (AST + ContextGraph)

- ContextGraph prevents evidence hallucination (wrong target context).
- AST prevents structure hallucination (invalid syntax and fabricated calls).
- Symbol-table and API checks catch non-existent references early.
- Net result: grounded and executable outputs.

---

# 7. Engineering Quality Improvement

- AST enables deterministic lint/policy enforcement at node level.
- Safe refactors become atomic AST transforms instead of full rewrites.
- Better test generation from function signatures and control paths.
- Higher reviewability through traceable structure and evidence.

---

# 8. Token and Cost Optimization

- ContextGraph reduces prompt bloat via minimal, high-signal retrieval.
- AST pruning keeps only signatures and relevant logic skeleton.
- Incremental AST-based repair replaces full regeneration retries.
- Typical reduction opportunity: large files compressed by 70% to 90% for task context.

### Cost view
Token cost = token price x (prompt tokens + completion tokens)

Largest controllable term is prompt tokens.

---

# 9. Time-to-Delivery Improvement

- Local AST parsing catches errors before runtime debugging loops.
- Constrained generation reduces retry cycles.
- XPath-like AST node addressing speeds targeted edits.
- More stable cycle time across complex, cross-module tasks.

---

# 10. High-Level Architecture

- ContextGraph runtime:
	- FastAPI surfaces for Admin, Viewer, Auth APIs, and MCP SSE.
	- FalkorDB for per-project graph intelligence.
	- Redis streams for indexing queue and status.
	- Redis cache and traces for fast retrieval and evaluation.
- AST layer sits in generation and validation path as a hard quality gate.

---

# 11. KPI Framework and ROI

- Reliability: hallucination proxy score, invalid symbol rate.
- Quality: defect escape rate, rework commits.
- Speed: median completion time, iterations per task.
- Cost: prompt tokens per successful change, cost per merged PR.

Pilot method: compare baseline vs ContextGraph+AST over 2 to 4 weeks on similar task classes.

---

# 12. Adoption Plan and Close

## Rollout in three phases

1. Pilot (1 to 2 repos, baseline instrumentation).
2. Team rollout (ContextGraph-first retrieval + AST validation gates).
3. Operating model (weekly KPI review, budget and policy tuning).

## Final message

ContextGraph + AST turns LLM coding from a probabilistic assistant into a controllable engineering system.
