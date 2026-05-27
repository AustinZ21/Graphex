# Environment Bootstrap Guide

Follow these exact steps to start the application locally from scratch. 
Never attempt to guess the start commands.

## ContextGraph Services Integration

Before starting the application, register with the ContextGraph ecosystem:

```bash
# 1. Register this project with ContextGraph
# Open CGA Admin UI: http://localhost:18001/admin
# Follow the guided setup to:
#   - Register this project in the ContextGraph catalog
#   - Retrieve CGA MCP server credentials and edge agent token
#   - Store credentials in .env (see step 2 below)

# 2. Configure ContextGraph environment variables
echo "CONTEXTGRAPH_MCP_SERVER_URL=http://localhost:18001/mcp/sse" >> .env
echo "CONTEXTGRAPH_BRIEFING_API_URL=http://localhost:18001/api/project/work-briefing/activity" >> .env
echo "CONTEXTGRAPH_INDEXING_POLICY=auto-incremental" >> .env
echo "CONTEXTGRAPH_EDGE_AGENT_TOKEN=<token-from-cga-admin>" >> .env
echo "CONTEXTGRAPH_PROJECT_ID=<project-id-from-cga-admin>" >> .env
```

After ContextGraph Edge Agent and CGA MCP Server are integrated, initialize a full repository index before starting feature work:

```text
Required one-time bootstrap indexing flow
1) Ensure `mcp-servers.json` contains the `cga-mcp-server` endpoint profile and receives project context from environment variables.
2) Run a full-project indexing call through ContextGraph MCP using:
	- project_id: CONTEXTGRAPH_PROJECT_ID
	- repo_path: repository root
	- changed_files: all tracked source and documentation files
3) Treat indexing as successful only after the ContextGraph service returns a successful completion status.
4) Configure periodic work briefing reports for service starts, feature milestones, validation runs, and releases.
```

For all later changes, run `index_repo_changes(repo_path)` through `cga-mcp-server` so modified source, documentation, configuration, and test content is indexed automatically.

## Auto-Enable CGA MCP Server Profile (ADC Standard)

ADC-compliant projects must keep the `cga-mcp-server` profile enabled in `.adc/contextgraph-edge-agent/mcp/mcp-servers.json`.

```text
Quick enable checklist for downstream projects
1) Copy the ADC template `.adc/contextgraph-edge-agent/mcp/mcp-servers.json` into the target project.
2) Confirm `cga-mcp-server` exists and points to a reachable CGA MCP SSE endpoint (default local dev endpoint: `http://localhost:18001/mcp/sse`).
3) Set environment variables before starting your IDE/agent host:
	- CONTEXTGRAPH_MCP_TOKEN
	- CONTEXTGRAPH_EDGE_AGENT_TOKEN
	- CONTEXTGRAPH_PROJECT_ID
4) Import the MCP file in your AI client so the server profile is loaded automatically.
5) Run one full-project index once, then switch to incremental indexing on changed files.
6) Confirm project progress reporting can reach `CONTEXTGRAPH_BRIEFING_API_URL` without logging raw tokens.
```

## Local Development Setup

```bash
# 3. Install dependencies
npm install

# 4. Setup the environment configuration
cp .env.example .env
# (Edit .env with values from ContextGraph registration above)

# 5. Start ContextGraph services
npm run contextgraph-mcp:start      # Starts src/contextgraph-mcp server (default: http://localhost:3001/mcp)
npm run contextgraph-edge:start     # Starts src/contextgraph-edge-agent service (default: http://localhost:3002/edges)

# 6. Start backing services (e.g. database, redis)
docker-compose up -d db redis

# 7. Run database migrations
npm run db:migrate

# 8. Start the local development server
npm run dev
```

## Verify ContextGraph Connectivity

Once running, verify local ContextGraph services are reachable:

```bash
# Check optional repository-local MCP bridge health (only if this repo ships one)
curl http://localhost:3001/mcp/health

# Check local edge agent health (src/contextgraph-edge-agent)
curl http://localhost:3002/edges/health

# Verify ContextGraph local dev API connectivity
curl http://localhost:18001/health
```


