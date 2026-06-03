# Autonomous Development Constitution Notes

The Autonomous Development Constitution (ADC) is the project-context governance model used by CGA. It keeps architecture, conventions, domain knowledge, and AI instructions close to the code while separating them from ordinary product documentation.

## Purpose

ADC exists to help AI coding agents and human developers acquire accurate project context quickly. It reduces the chance that an agent writes code that violates local conventions or misses historical architecture decisions.

CGA is designed to work well with ADC-style repositories because CGA indexes the code and exposes graph-aware retrieval, while ADC defines the rules, vocabulary, and workflows that agents should follow.

## Repository Boundary

An ADC-enabled repository keeps governance context in a hidden `.adc/` directory at the project root.

```text
project-root/
├── .adc/
├── src/
├── docs/
├── tests/
└── ...
```

Important boundaries:

- `.adc/` is internal AI governance and context.
- `docs/` is user-facing, API, and project documentation.
- `src/`, `docs/`, `tests/`, and other application folders remain root-level siblings of `.adc/`.
- Application source and public documentation should not be placed inside `.adc/`.

## Core ADC Files

```text
.adc/
├── index.md
├── bootstrap.md
├── prompt-rules.md
├── planning/
│   ├── status.md
│   ├── project-roadmap.md
│   └── development-phases.md
├── standards/
│   ├── conventions/
│   ├── checklists/
│   └── runbooks/
├── knowledge/
│   ├── glossary.md
│   ├── known-issues.md
│   ├── amendments.md
│   ├── adr/
│   └── diagrams/
└── contextgraph-edge-agent/
    ├── tasks/
    ├── scratchpad/
    ├── mcp/
    └── skills/
```

### `index.md`

The main context entry point. It should include structured metadata, project background, core modules, and environment requirements.

```yaml
---
project-name: "Your Project Name"
version: "1.0.0"
description: "A concise description of the project's core business value."
tech-stack:
  - React 18
  - Node.js 20
  - PostgreSQL
architecture-style: "Microservices / Monolith / Event-Driven"
entry-points:
  - src/main.ts
---
```

### `prompt-rules.md`

The mandatory AI instruction layer. This file captures strict rules such as coding conventions, security constraints, test expectations, and context-loading requirements.

### `bootstrap.md`

The exact commands needed to install dependencies, start local services, run databases, and launch development servers.

### `planning/`

Planning documents keep agents aligned with current phase, roadmap, active goals, and recent major changes.

### `standards/conventions/`

Conventions are split by domain so agents can load only the relevant rules for a task. Common domains include frontend, backend, data engineering, performance, observability, security, DevOps, testing, and structure.

### `knowledge/`

Knowledge documents preserve terminology, known issues, no-touch zones, architecture decisions, amendments, and living diagrams.

### `contextgraph-edge-agent/`

This workspace is for orchestration state, MCP wiring, scratchpad notes, task queues, and specialized skills. Canonical requirements and architecture decisions should remain in planning, standards, and knowledge files.

## Agent Initialization Protocol

ADC-aware agents should follow this high-level order before making non-trivial changes:

1. Read `.adc/index.md`, `.adc/planning/status.md`, and `.adc/planning/development-phases.md`.
2. Read `.adc/knowledge/known-issues.md` before planning refactors.
3. Read `.adc/prompt-rules.md` and follow mandatory conventions.
4. Read `.adc/knowledge/glossary.md` for domain-specific names and acronyms.
5. Check `.adc/contextgraph-edge-agent/skills/` for project-specific workflows.
6. Check `.adc/contextgraph-edge-agent/mcp/` for MCP server wiring.
7. Complete relevant `.adc/standards/checklists/` before finalizing commits or pull requests.
8. Update living Mermaid diagrams when architecture, data flow, or schema changes.

## ContextGraph And MCP Policy

ADC-compliant projects can provide a preconfigured `cga-mcp-server` entry in `.adc/contextgraph-edge-agent/mcp/mcp-servers.json` so agents can load CGA retrieval tools consistently.

For local CGA development, the default SSE MCP endpoint is:

```text
http://localhost:18001/mcp/sse
```

Use `Authorization` and `X-Project-ID` headers when project-scoped access is required.

ContextGraph MCP integrations are for retrieval, indexing, and external context operations. Local build, test, and deployment execution should remain on native project tooling.

ContextGraph credentials such as `CONTEXTGRAPH_PROJECT_ID`, `CONTEXTGRAPH_MCP_TOKEN`, and `CONTEXTGRAPH_EDGE_AGENT_TOKEN` must be injected through environment variables and must not be committed.

## Governance Patterns

- Store project vocabulary in `knowledge/glossary.md` so agents use correct names in code and docs.
- Store historical decisions in `knowledge/adr/` so agents avoid re-proposing rejected architectures.
- Store technical debt and no-touch zones in `knowledge/known-issues.md`.
- Store architecture and data-flow diagrams in Mermaid under `knowledge/diagrams/`.
- Treat changes to ADC rules as governance changes that require human review.

## Quick Start Skeleton For New ADC Repositories

The following command creates a bare ADC skeleton for an existing codebase. Populate the files with the actual project rules before relying on them for agent automation.

```bash
mkdir -p .adc/planning .adc/standards/conventions .adc/standards/checklists .adc/standards/runbooks .adc/knowledge/adr .adc/knowledge/diagrams .adc/contextgraph-edge-agent/skills .adc/contextgraph-edge-agent/mcp .adc/contextgraph-edge-agent/tasks/todo .adc/contextgraph-edge-agent/tasks/in-progress .adc/contextgraph-edge-agent/tasks/done .adc/contextgraph-edge-agent/scratchpad tests .github
touch .adc/index.md .adc/bootstrap.md .adc/prompt-rules.md .adc/planning/status.md .adc/planning/project-roadmap.md .adc/planning/development-phases.md .adc/knowledge/glossary.md .adc/knowledge/known-issues.md .adc/knowledge/amendments.md .adc/standards/conventions/structure.md .adc/standards/conventions/frontend.md .adc/standards/conventions/backend.md .adc/standards/conventions/data-engineering.md .adc/standards/conventions/performance.md .adc/standards/conventions/observability.md .adc/standards/conventions/security.md .adc/standards/conventions/devops.md .adc/standards/conventions/testing.md .adc/contextgraph-edge-agent/mcp/mcp-servers.json .adc/standards/checklists/pr-review.md .adc/standards/runbooks/001-common-errors.md .adc/contextgraph-edge-agent/scratchpad/session.md .adc/contextgraph-edge-agent/tasks/todo/TASK-001.md .adcignore .cursorrules .windsurfrules .clinerules .roomadesrules .aider.rules .codexrules .antigravityrules .codeiumrules .codyrules .github/copilot-instructions.md
```