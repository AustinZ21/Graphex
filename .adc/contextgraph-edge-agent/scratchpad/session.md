# Session Scratchpad

# Reserved for temporary AI handoff notes. Keep untracked and non-canonical.
- 2026-04-19: Added CG MCP server-side git-aware indexing design.
- New MCP tool: `index_repo_changes(repo_path, include_untracked=true, auto_full_on_destructive=true)`.
- Rationale: periodic/manual reindex is a cross-project operational gap; moved change discovery into CG MCP server instead of requiring each downstream repo to script it.
- Safety note: deletes/renames auto-promote to full index because current incremental pipeline does not clean stale symbols for disappeared files.
- 2026-04-19 update: native pipeline cleanup added for repo/file subgraphs.
- `IndexPipeline.index_full()` now clears the repo subgraph before rebuild.
- `IndexPipeline.index_incremental()` now removes stale file-local graph data for missing, deleted, renamed, and rewritten files before re-writing current symbols/variables/edges.
- `index_repo_changes()` now defaults to incremental even for destructive git changes; `auto_full_on_destructive=true` is optional fallback only.
- 2026-04-20 update: Admin queue telemetry added to `/auth/projects/index-status`.
- `IndexJobStatus` now includes `queue_position` and `eta_seconds` for best-effort queue wait estimation.
- Queue snapshot is sourced from Redis status keys via `JobConsumer.get_queue_snapshot()`.
- Fixed repo path variant issue in status aggregation: now merges jobs across all candidate repo paths (`D:/Repos/...` + `/repos/...`) and selects the newest `updated_at` record.
- Frontend project status text now appends queue/ETA when available (e.g., `pending · q#2 · ETA ~75s`).
- 2026-04-20 update: Reworked project indexing UI into a shipping-style tracker.
- Admin project rows now render all lifecycle nodes (`Queued`, `Indexing`, `Complete`, `Failed`) at once and pulse the current active node until a terminal state is reached.
- Status detail chips now always show `Status`, `Queue`, `ETA`, `Scope`, and `Source`, even when queue telemetry is unavailable (`q#-`, `ETA -`).
- 2026-04-20 update: expanded project panel now includes `Recent Index Events` history built from the latest 5 jobs returned by `/auth/projects/index-status`.
- Added backend `recent_jobs` payload on `ProjectIndexStatus` and kept `latest_job` as the headline status for the main row.
- 2026-04-20 final tracking UX pass:
- Strengthened tracker connectors with explicit completed/current progress lines.
- Added relative time labels (`just now`, `15s ago`, `1m ago`, etc.) for queued/updated timestamps in recent job history.
- Failed history events now expose `Retry` and expandable `Show failure details` UI, reusing the existing project reindex endpoint.
- 2026-04-20 tracker alignment tweak: changed the main tracker grid to `inline-grid` with content-sized columns and left-aligned parent panel so the entire shipping tracker sits flush left instead of stretching across the full cell width.
- Validation blocker: required Docker rebuild via remote daemon `tcp://192.168.1.239:2375` timed out while resolving `falkordb/falkordb:latest`, so live browser verification of the alignment change is pending until the remote daemon is reachable again.
- 2026-04-20 local verification update: local `docker compose --profile dev up -d --build api-dev` succeeded, and the served admin HTML now contains the left-alignment CSS for both the main tracker (`inline-grid`, parent `align-items: flex-start`) and the expanded `Recent Index Events` timeline (`width: min(100%, 760px)`, `justify-content: flex-start`, `align-self: flex-start`).
- 2026-04-20 wording cleanup: changed the queue placeholder from `q#-` to `—` in both the main tracker summary and `Recent Index Events` so the UI no longer exposes an internal-looking placeholder when no queue position is available. Also changed `ETA -` to `—` for visual consistency.
- 2026-04-20 conditional field visibility: Queue and ETA fields are now hidden when job status is not pending/processing, keeping the interface cleaner by only showing queue/ETA info when relevant (during active indexing).
# Agent Session State / Brain Dump

**Objective:**
Write down exactly what you are currently doing, the last known successful step, and any immediate blockers.
This ensures the NEXT agent handling this repository knows exactly where you left off.

- **Current Task:** 2026-05-07 ContextGraph HPS context-quality benchmark.
- **Last Action Taken:** Added deterministic Hallucination Pressure Score scoring, REST/MCP benchmark surfaces, a CodexCLI/ClaudeCLI JSONL manifest, a report runner, generated JSON/Markdown reports, and README/docs updates.
- **Failing Tests / Errors:** Normal pytest collection still hits local `pytest_asyncio` AttributeError before test execution; new runner initially needed an explicit `src/` import path fix when launched with `python -m src.scripts...`.
- **Next Steps:** Focused HPS tests passed with plugin autoload disabled and pytest addopts cleared; run full suite after the local pytest plugin mismatch is resolved.
- 2026-05-08 update: Added a standalone large graph viewer under `src/viewer` and a protected `/api/viewer/graphs/{project_name}` API for stats plus chunked graph loading.
- 2026-05-08 update: Merged the graph viewer into the Admin SPA as an admin-only `Graph Viewer` tab backed by the same `/viewer/` static app and shared `cg_jwt` session.
- 2026-05-08 update: Added relationship-type colors to the viewer: CALLS, IMPORTS, DEFINES, CONTAINS, USES_VARIABLE, and FLOWS_TO now use distinct node/link colors with a legend.
- Library decision: selected MIT-licensed `@cosmos.gl/graph` for GPU/WebGL large network rendering; the API defaults to 50k-edge chunks and caps chunks at 100k edges so million-scale graphs are loaded progressively instead of as one JSON payload.
- Integration note: FastAPI now serves the viewer at `/viewer`; it reuses the Admin UI `cg_jwt` token or accepts a pasted admin JWT.
