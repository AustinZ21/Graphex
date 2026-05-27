---
project-name: "Agentic Boilerplate Project"
version: "1.0.0"
description: "A reference implementation of the Autonomous Development Constitution (ADC)."
tech-stack:
  - React 18
  - Node.js 20
  - PostgreSQL
architecture-style: "Microservices"
entry-points:
  - src/main.ts
---

# Project Overview
This project serves as a reference implementation of the ADC standard. 
It defines the exact rules, constraints, and architecture that AI Agents must follow.

## Core Modules
- `src/api`: Core backend services
- `src/web`: Frontend React application
- `src/contextgraph-edge-agent`: ContextGraph Edge Agent (local execution and orchestration)

## Required Integrations
This project **MUST** integrate with the ContextGraph ecosystem:
- **ContextGraph Project**: Central repository and artifact management system (registration via CGA Admin UI at `http://localhost:18001/admin`)
- **ContextGraph Edge Agent** (`src/contextgraph-edge-agent`): Local execution and orchestration agent
- **CGA MCP Server**: Model Context Protocol endpoint for programmatic ContextGraph access (default local dev SSE endpoint: `http://localhost:18001/mcp/sse`)
- **CGA MCP Server Profile Standard**: `.adc/contextgraph-edge-agent/mcp/mcp-servers.json` MUST include a `cga-mcp-server` entry so ADC-based projects can auto-load CGA MCP wiring.
- **Initial ContextGraph Indexing**: Immediately after ContextGraph Edge Agent + CGA MCP Server integration, run full-project indexing once so retrieval/review tools can access the entire repository context.

ContextGraph MCP access is endpoint-first by default. A local MCP implementation is optional and repository-specific.

## Environment Requirements
Refer to `bootstrap.md` for exact start-up commands.


