# ContextGraph Development Strategy (Python First)

## 1. Goal

Build a Python-first indexing platform that uses Graph DB + MCP server client + Docker to help agents locate code in large repositories more accurately, reduce hallucinations, improve code quality, and lower retrieval time cost.

## 2. Success Metrics

- Retrieval precision at top-5 (P@5) >= 0.85 on curated query set.
- End-to-end query latency P95 <= 1.5s for indexed repositories up to target project size.
- Incremental indexing throughput >= 5,000 LOC/min under default local profile.
- Hallucination proxy reduction >= 30% versus baseline keyword search workflow.

## 3. Product Scope

- In scope:
  - Repository ingestion and parsing for Python-first implementation.
  - Graph schema for code entities and relationships.
  - MCP client orchestration for indexing and retrieval workflows.
  - Dockerized local and CI execution.
  - Evaluation harness for retrieval quality and latency.
- Out of scope (phase 1):
  - Multi-tenant production auth.
  - Large-scale distributed indexing.
  - UI-heavy management console.

## 4. Architecture Strategy

- Core components:
  - Indexer service (Python): parse source files, extract entities, build edges.
  - Graph adapter (Python): abstract graph storage operations and query plans.
  - Retrieval service (Python): hybrid retrieval path (graph traversal + lexical/semantic fallback).
  - MCP integration layer: standardized tools for index, refresh, and retrieve.
  - Evaluation runner: benchmark accuracy/latency regressions.
- Deployment model:
  - Docker Compose for local stack composition.
  - Separate containers for app service and graph backend.
  - Resource limits and health checks on all critical services.

## 5. Graph Data Model

- Primary nodes:
  - Repository
  - File
  - Symbol (class/function/method/variable)
  - Module/Package
  - Commit (optional phase 2)
  - DocumentChunk (for long-file context windows)
- Primary edges:
  - CONTAINS (Repository -> File, File -> Symbol)
  - IMPORTS (Module/File -> Module/File)
  - DEFINES (File -> Symbol)
  - CALLS (Symbol -> Symbol)
  - REFERENCES (File/Symbol -> Symbol)
  - DEPENDS_ON (Service/Module -> Module)
- Indexing policy:
  - First run: full-project index.
  - Later runs: incremental index by changed files only.
  - Rebuild conditions: schema changes, parser major upgrade, index corruption.

## 6. MCP Client Strategy

- Expose stable MCP tool set:
  - index_full(repo_path)
  - index_incremental(repo_path, changed_paths)
  - find_symbol(symbol_name, scope)
  - find_callers(symbol_id)
  - find_callees(symbol_id)
  - retrieve_context(query, constraints)
- Reliability rules:
  - Timeouts and retries with bounded backoff.
  - Deterministic tool outputs with explicit schema.
  - Structured error taxonomy for agent fallback behavior.

## 7. Python Engineering Standards

- Runtime target:
  - Python 3.11+.
- Project structure:
  - Domain logic under src/.
  - Tests under src/tests/ (current repository baseline).
  - Scripts under src/scripts/.
- Quality gates:
  - Formatting: black.
  - Linting: ruff.
  - Type checking: mypy (progressive strict mode).
  - Test framework: pytest.
- Reliability patterns:
  - Typed models for MCP contracts.
  - Idempotent incremental indexing pipeline.
  - Strong observability with structured logs and correlation IDs.

## 8. Docker Strategy

- Compose profiles:
  - dev: fast feedback, mounted source, verbose logs.
  - test: deterministic test execution with fixed dependencies.
  - ci: minimal reproducible environment for policy checks.
- Container rules:
  - Pin image tags.
  - Run non-root where possible.
  - Use explicit CPU/memory limits in Compose.
  - Health checks required for graph and app services.

## 9. Phased Delivery Plan

- Phase 1 (foundation, 1-2 weeks):
  - Graph schema v1.
  - Full indexing pipeline.
  - Basic MCP tools for symbol/file retrieval.
  - Baseline evaluation dataset.
- Phase 2 (quality, 1-2 weeks):
  - Incremental indexing.
  - Call graph and dependency graph enhancements.
  - P@5 and latency dashboards.
- Phase 3 (optimization, 1-2 weeks):
  - Query planner tuning.
  - Cache layer for hot queries.
  - Hallucination-reduction evaluation loop with agent traces.

## 10. Risk Management

- Risk: parser inaccuracies on polyglot repositories.
  - Mitigation: language adapters and parser conformance tests.
- Risk: graph bloat and slow traversals.
  - Mitigation: edge cardinality limits, compaction jobs, and query profiling.
- Risk: MCP instability during long indexing jobs.
  - Mitigation: resumable jobs and checkpointing.

## 11. Security Baseline

- Deployment keys must remain under .deploy-keys/ and never be committed.
- Secret material must be injected at runtime, not stored in repository files.
- Add pre-commit and CI checks to block accidental key leakage patterns.

## 12. Immediate Next Actions

- Add Python dependency set for formatter/linter/type/test tools.
- Implement graph schema v1 and indexing domain models.
- Create MCP contracts and test fixtures for retrieval APIs.
- Add benchmark script for P@5 and latency tracking.
