"""ContextGraph MCP Server – exposes indexing and retrieval tools.

Phase 1 tools
-------------
index_full / index_incremental  - enqueue jobs via MQ
find_symbol / find_callers / find_callees / retrieve_context  - graph reads

Phase 2 additions
-----------------
find_call_graph(qualified_name) - direct call graph traversal
get_stats()                     - symbol / file / edge counts

Phase 3 additions
-----------------
run_eval()      - P@5 + latency benchmark report
clear_cache()   - invalidate Redis query cache

Read tools are cache-aware (check → serve or populate).
All read tool calls are trace-recorded for hallucination-proxy scoring.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import structlog
from mcp.server.fastmcp import FastMCP

from backend.agent.query_strategy import run_cg_first_strategy
from backend.graph.client import GraphClient
from backend.graph import schema as S
from backend.tools.producer import MCPProducer

log = structlog.get_logger()

mcp = FastMCP("contextgraph")

_graph: GraphClient | None = None
_producer: MCPProducer | None = None
_cache = None           # QueryCache | None  – set via init()
_recorder = None        # TraceRecorder | None  – set via init()
_repo_root = Path(os.getenv("CONTEXTGRAPH_REPO_ROOT", ".")).resolve()


def init(
    graph: GraphClient,
    producer: MCPProducer,
    cache=None,
    recorder=None,
) -> None:
    """Wire dependencies after app startup."""
    global _graph, _producer, _cache, _recorder
    _graph = graph
    _producer = producer
    _cache = cache
    _recorder = recorder


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cached_read(tool: str, args: dict, fetch_fn):
    """Check cache → call fetch_fn → store → record trace → return."""
    if _cache:
        hit = _cache.get(tool, args)
        if hit is not None:
            return hit
    t0 = time.perf_counter()
    result = fetch_fn()
    latency_ms = (time.perf_counter() - t0) * 1000.0
    if _cache:
        _cache.set(tool, args, result)
    if _recorder:
        _recorder.record(tool, args, result, latency_ms)
    return result


def _read_symbol_snippet(file_path: str, line_start: int, line_end: int, context_lines: int = 2, max_chars: int = 900) -> str:
    path = Path(file_path)
    if not path.is_absolute():
        path = (_repo_root / file_path).resolve()
    if not path.exists() or not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    if not lines:
        return ""

    start_idx = max(0, int(line_start) - 1 - context_lines)
    end_idx = min(len(lines), int(line_end) + context_lines)
    snippet = "\n".join(lines[start_idx:end_idx]).strip()
    if len(snippet) > max_chars:
        return snippet[: max_chars - 3] + "..."
    return snippet


def _summarize_symbol(symbol_type: str, qualified_name: str, file_path: str, line_start: int, line_end: int) -> str:
    location = f"{file_path}:{line_start}-{line_end}"
    return f"{symbol_type} {qualified_name} at {location}"


def _fetch_relation_summary(qualified_name: str, limit: int = 3) -> dict:
    if not _graph:
        return {"callers": [], "callees": [], "callers_count": 0, "callees_count": 0}

    callers_result = _graph.query(
        S.QUERY_FIND_CALLERS,
        {"qualified_name": qualified_name, "limit": limit},
    )
    callees_result = _graph.query(
        S.QUERY_FIND_CALLEES,
        {"qualified_name": qualified_name, "limit": limit},
    )
    callers = [row[0] for row in callers_result.result_set]
    callees = [row[0] for row in callees_result.result_set]
    return {
        "callers": callers,
        "callees": callees,
        "callers_count": len(callers),
        "callees_count": len(callees),
    }


# ---------------------------------------------------------------------------
# Write tools (async – go through MQ)
# ---------------------------------------------------------------------------

@mcp.tool()
async def index_full(repo_path: str) -> dict:
    """Enqueue a full index job for the given repository path."""
    if not _producer:
        raise RuntimeError("MCP server not initialized")
    submitted = await _producer.submit_full_index(repo_path)
    # Invalidate cache so stale reads are avoided after re-index
    if _cache:
        _cache.invalidate_all()
    return {
        "status": "queued",
        "stream_id": submitted["stream_id"],
        "job_id": submitted["job_id"],
        "repo_path": repo_path,
    }


@mcp.tool()
async def index_incremental(repo_path: str, changed_paths: list[str]) -> dict:
    """Enqueue an incremental index job for a list of changed files."""
    if not _producer:
        raise RuntimeError("MCP server not initialized")
    submitted = await _producer.submit_incremental_index(repo_path, changed_paths)
    if _cache:
        _cache.invalidate_all()
    return {
        "status": "queued",
        "stream_id": submitted["stream_id"],
        "job_id": submitted["job_id"],
        "changed_count": len(changed_paths),
    }


@mcp.tool()
async def get_index_job_status(job_id: str) -> dict:
    """Get status for an indexing job id."""
    if not _producer:
        raise RuntimeError("MCP server not initialized")
    status = await _producer.get_job_status(job_id)
    if status is None:
        return {"job_id": job_id, "status": "not_found"}
    return status


@mcp.tool()
async def wait_for_index_ready(
    job_id: str,
    timeout_sec: float = 120.0,
    poll_interval_sec: float = 1.0,
) -> dict:
    """Wait until an indexing job reaches terminal state (done or failed)."""
    if not _producer:
        raise RuntimeError("MCP server not initialized")
    return await _producer.wait_for_job_status(
        job_id,
        timeout_sec=timeout_sec,
        poll_interval_sec=poll_interval_sec,
    )


# ---------------------------------------------------------------------------
# Read tools (sync – direct graph query, cache-aware)
# ---------------------------------------------------------------------------

@mcp.tool()
def find_symbol(name: str, limit: int = 20) -> list[dict]:
    """Find symbols by name or qualified name fragment."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")

    def _fetch():
        result = _graph.query(S.QUERY_FIND_SYMBOL, {"name": name, "limit": limit})
        return [
            {
                "qualified_name": row[0],
                "symbol_type": row[1],
                "file_path": row[2],
                "line_start": row[3],
                "line_end": row[4],
            }
            for row in result.result_set
        ]

    return _cached_read("find_symbol", {"name": name, "limit": limit}, _fetch)


@mcp.tool()
def find_callers(qualified_name: str, limit: int = 20) -> list[dict]:
    """Return all symbols that call the given qualified name."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")

    def _fetch():
        result = _graph.query(
            S.QUERY_FIND_CALLERS, {"qualified_name": qualified_name, "limit": limit}
        )
        return [
            {"caller": row[0], "file_path": row[1], "line_start": row[2]}
            for row in result.result_set
        ]

    return _cached_read(
        "find_callers", {"qualified_name": qualified_name, "limit": limit}, _fetch
    )


@mcp.tool()
def find_callees(qualified_name: str, limit: int = 20) -> list[dict]:
    """Return all symbols called by the given qualified name."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")

    def _fetch():
        result = _graph.query(
            S.QUERY_FIND_CALLEES, {"qualified_name": qualified_name, "limit": limit}
        )
        return [
            {"callee": row[0], "file_path": row[1], "line_start": row[2]}
            for row in result.result_set
        ]

    return _cached_read(
        "find_callees", {"qualified_name": qualified_name, "limit": limit}, _fetch
    )


@mcp.tool()
def retrieve_context(query: str, limit: int = 10) -> list[dict]:
    """Retrieve relevant code context for an agent query string."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")

    def _fetch():
        result = _graph.query(S.QUERY_RETRIEVE_CONTEXT, {"query": query, "limit": limit})
        items: list[dict] = []
        for row in result.result_set:
            qualified_name = row[0]
            symbol_type = row[1]
            file_path = row[2]
            line_start = row[3]
            line_end = row[4]
            snippet = _read_symbol_snippet(file_path, line_start, line_end)
            relations = _fetch_relation_summary(qualified_name)
            items.append(
                {
                    "qualified_name": qualified_name,
                    "symbol_type": symbol_type,
                    "file_path": file_path,
                    "line_start": line_start,
                    "line_end": line_end,
                    "summary": _summarize_symbol(symbol_type, qualified_name, file_path, line_start, line_end),
                    "snippet": snippet,
                    **relations,
                }
            )
        return items

    return _cached_read("retrieve_context", {"query": query, "limit": limit}, _fetch)


# ---------------------------------------------------------------------------
# Phase 2: call graph traversal + stats
# ---------------------------------------------------------------------------

@mcp.tool()
def find_call_graph(qualified_name: str, depth: int = 2) -> dict:
    """Return the full call graph (callers + callees) up to *depth* hops."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")

    def _fetch():
        callers_result = _graph.query(
            S.QUERY_FIND_CALLERS, {"qualified_name": qualified_name, "limit": 50}
        )
        callees_result = _graph.query(
            S.QUERY_FIND_CALLEES, {"qualified_name": qualified_name, "limit": 50}
        )
        return {
            "symbol": qualified_name,
            "callers": [row[0] for row in callers_result.result_set],
            "callees": [row[0] for row in callees_result.result_set],
        }

    return _cached_read(
        "find_call_graph", {"qualified_name": qualified_name, "depth": depth}, _fetch
    )


@mcp.tool()
def get_stats() -> dict:
    """Return graph statistics: symbol count, file count, CALLS edge count."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")

    def _fetch():
        sym = _graph.query("MATCH (s:Symbol) RETURN count(s)").result_set
        fil = _graph.query("MATCH (f:File) RETURN count(f)").result_set
        calls = _graph.query("MATCH ()-[c:CALLS]->() RETURN count(c)").result_set
        return {
            "symbols": sym[0][0] if sym else 0,
            "files": fil[0][0] if fil else 0,
            "call_edges": calls[0][0] if calls else 0,
        }

    return _cached_read("get_stats", {}, _fetch)


# ---------------------------------------------------------------------------
# Phase 3: eval + cache management
# ---------------------------------------------------------------------------

@mcp.tool()
def run_eval() -> dict:
    """Run the P@5 + latency benchmark and return the report."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    from backend.eval.runner import EvalRunner
    runner = EvalRunner(_graph)
    return runner.run().as_dict()


@mcp.tool()
def clear_cache() -> dict:
    """Invalidate all cached query results."""
    if not _cache:
        return {"status": "no_cache_configured", "deleted": 0}
    deleted = _cache.invalidate_all()
    log.info("cache.cleared", keys_deleted=deleted)
    return {"status": "ok", "deleted": deleted}


# ---------------------------------------------------------------------------
# Aggregation & architecture analysis
# ---------------------------------------------------------------------------

@mcp.tool()
def get_architecture_overview() -> dict:
    """Get high-level architecture stats: file count, symbols, languages, interconnectedness."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    
    def _fetch():
        result = _graph.query(S.QUERY_ARCHITECTURE_OVERVIEW)
        if result.result_set:
            row = result.result_set[0]
            return {
                "total_files": row[0],
                "total_symbols": row[1],
                "languages": row[2],
                "files_with_incoming_calls": row[3],
                "avg_symbols_per_file": round(float(row[4]) if row[4] else 0, 2),
                "avg_callers_per_file": round(float(row[5]) if row[5] else 0, 2),
            }
        return {"error": "no_data"}
    
    return _cached_read("get_architecture_overview", {}, _fetch)


@mcp.tool()
def get_key_modules(limit: int = 10) -> list[dict]:
    """Find key modules (files with high importance based on symbols and incoming calls)."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    
    def _fetch():
        result = _graph.query(S.QUERY_KEY_FILES, {"limit": limit})
        return [
            {
                "file_path": row[0],
                "language": row[1],
                "symbol_count": row[2],
                "incoming_calls": row[3],
                "symbols_with_calls": row[4],
                "importance_score": round(float(row[5]), 2),
            }
            for row in result.result_set
        ]
    
    return _cached_read("get_key_modules", {"limit": limit}, _fetch)


@mcp.tool()
def get_file_stats(file_path: str) -> dict:
    """Get detailed stats for a specific file: symbols, incoming calls, outgoing calls."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    
    def _fetch():
        result = _graph.query(S.QUERY_FILE_STATS, {"file_path": file_path})
        if result.result_set:
            row = result.result_set[0]
            return {
                "file_path": file_path,
                "symbol_count": row[0],
                "incoming_calls": row[1],
                "symbols_with_outgoing_calls": row[2],
            }
        return {"file_path": file_path, "error": "not_found"}
    
    return _cached_read("get_file_stats", {"file_path": file_path}, _fetch)


@mcp.tool()
def analyze_dependencies(limit: int = 20) -> list[dict]:
    """Analyze top file dependencies: which files call which, and how often."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    
    def _fetch():
        result = _graph.query(S.QUERY_MODULE_DEPENDENCIES, {"limit": limit})
        return [
            {
                "from_file": row[0],
                "to_file": row[1],
                "caller_symbols": row[2],
                "callee_symbols": row[3],
            }
            for row in result.result_set
        ]
    
    return _cached_read("analyze_dependencies", {"limit": limit}, _fetch)


@mcp.tool()
def find_dependency_chain(source_path: str, target_path: str) -> dict:
    """Analyze how source_path reaches target_path through call chains (hops)."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    
    def _fetch():
        result = _graph.query(
            S.QUERY_FILE_DEPENDENCY_CHAIN,
            {"source_path": source_path, "target_path": target_path},
        )
        if result.result_set:
            chains = [
                {"hops": row[0], "path_count": row[1]}
                for row in result.result_set
            ]
            return {
                "source_path": source_path,
                "target_path": target_path,
                "chains": chains,
                "closest_distance": chains[0]["hops"] if chains else None,
            }
        return {
            "source_path": source_path,
            "target_path": target_path,
            "chains": [],
            "closest_distance": None,
        }
    
    return _cached_read(
        "find_dependency_chain",
        {"source_path": source_path, "target_path": target_path},
        _fetch,
    )


# ---------------------------------------------------------------------------
# Import tracking & external dependencies
# ---------------------------------------------------------------------------

@mcp.tool()
def get_file_imports(file_path: str) -> list[dict]:
    """Get all local imports from a specific file."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    
    def _fetch():
        result = _graph.query(S.QUERY_FILE_IMPORTS, {"file_path": file_path})
        return [
            {"target_file": row[0], "language": row[1]}
            for row in result.result_set
        ]
    
    return _cached_read("get_file_imports", {"file_path": file_path}, _fetch)


@mcp.tool()
def get_file_dependents(file_path: str) -> list[dict]:
    """Get all files that import this file."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    
    def _fetch():
        result = _graph.query(S.QUERY_IMPORT_DEPENDENTS, {"file_path": file_path})
        return [
            {"dependent_file": row[0], "language": row[1]}
            for row in result.result_set
        ]
    
    return _cached_read("get_file_dependents", {"file_path": file_path}, _fetch)


@mcp.tool()
def get_dependency_overview(limit: int = 30) -> list[dict]:
    """Get dependency graph: which files import which (top by count)."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    
    def _fetch():
        result = _graph.query(S.QUERY_DEPENDENCY_GRAPH, {"limit": limit})
        return [
            {
                "from_file": row[0],
                "to_file": row[1],
                "from_language": row[2],
                "to_language": row[3],
            }
            for row in result.result_set
        ]
    
    return _cached_read("get_dependency_overview", {"limit": limit}, _fetch)


@mcp.tool()
def analyze_import_surface(limit: int = 15) -> list[dict]:
    """Analyze files by import dependencies: most imported, most importing."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    
    def _fetch():
        result = _graph.query(S.QUERY_EXTERNAL_DEPENDENCIES, {"limit": limit})
        return [
            {
                "file_path": row[0],
                "language": row[1],
                "internal_imports": row[2],
                "incoming_imports": row[3],
            }
            for row in result.result_set
        ]
    
    return _cached_read("analyze_import_surface", {"limit": limit}, _fetch)


@mcp.tool()
def strategy_query(
    query: str,
    graph_top_k: int = 8,
    min_graph_hits: int = 3,
    token_budget: int = 1800,
    relation_depth: int = 1,
    fallback_max_files: int = 3,
) -> dict:
    """Run the default CG-first agent routing strategy through MCP itself."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    return run_cg_first_strategy(
        query=query,
        repo_root=_repo_root,
        retrieve_graph_hits=retrieve_context,
        get_call_graph=find_call_graph,
        graph_top_k=max(1, graph_top_k),
        min_graph_hits=max(1, min_graph_hits),
        token_budget=max(200, token_budget),
        relation_depth=max(1, relation_depth),
        fallback_max_files=max(1, fallback_max_files),
        source_label="contextgraph-server",
    )

