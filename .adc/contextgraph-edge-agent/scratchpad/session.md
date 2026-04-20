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
# Agent Session State / Brain Dump

**Objective:**
Write down exactly what you are currently doing, the last known successful step, and any immediate blockers.
This ensures the NEXT agent handling this repository knows exactly where you left off.

- **Current Task:** 
- **Last Action Taken:** 
- **Failing Tests / Errors:** 
- **Next Steps:** 
