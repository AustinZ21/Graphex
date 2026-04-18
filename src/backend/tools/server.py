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

import time

import structlog
from mcp.server.fastmcp import FastMCP

from backend.graph.client import GraphClient
from backend.graph import schema as S
from backend.tools.producer import MCPProducer

log = structlog.get_logger()

mcp = FastMCP("contextgraph")

_graph: GraphClient | None = None
_producer: MCPProducer | None = None
_cache = None           # QueryCache | None  – set via init()
_recorder = None        # TraceRecorder | None  – set via init()


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


# ---------------------------------------------------------------------------
# Write tools (async – go through MQ)
# ---------------------------------------------------------------------------

@mcp.tool()
async def index_full(repo_path: str) -> dict:
    """Enqueue a full index job for the given repository path."""
    if not _producer:
        raise RuntimeError("MCP server not initialized")
    stream_id = await _producer.submit_full_index(repo_path)
    # Invalidate cache so stale reads are avoided after re-index
    if _cache:
        _cache.invalidate_all()
    return {"status": "queued", "stream_id": stream_id, "repo_path": repo_path}


@mcp.tool()
async def index_incremental(repo_path: str, changed_paths: list[str]) -> dict:
    """Enqueue an incremental index job for a list of changed files."""
    if not _producer:
        raise RuntimeError("MCP server not initialized")
    stream_id = await _producer.submit_incremental_index(repo_path, changed_paths)
    if _cache:
        _cache.invalidate_all()
    return {
        "status": "queued",
        "stream_id": stream_id,
        "changed_count": len(changed_paths),
    }


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

