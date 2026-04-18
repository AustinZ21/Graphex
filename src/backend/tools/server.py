"""ContextGraph MCP Server – exposes indexing and retrieval tools.

Tools
-----
index_full(repo_path)
    Enqueue a full-repository index job via the MQ (client side producer).

index_incremental(repo_path, changed_paths)
    Enqueue an incremental index job for a list of changed files.

find_symbol(name, limit)
    Search the graph for symbols matching *name*.

find_callers(qualified_name, limit)
    Return all symbols that call the given qualified name.

find_callees(qualified_name, limit)
    Return all symbols called by the given qualified name.

retrieve_context(query, limit)
    Hybrid retrieval: graph traversal on matching symbols for agent context.
"""

from __future__ import annotations

import structlog
from mcp.server.fastmcp import FastMCP

from backend.graph.client import GraphClient
from backend.graph import schema as S
from backend.tools.producer import MCPProducer

log = structlog.get_logger()

mcp = FastMCP("contextgraph")

_graph: GraphClient | None = None
_producer: MCPProducer | None = None


def init(graph: GraphClient, producer: MCPProducer) -> None:
    """Wire dependencies after app startup."""
    global _graph, _producer
    _graph = graph
    _producer = producer


# ---------------------------------------------------------------------------
# Write tools (async – go through MQ)
# ---------------------------------------------------------------------------

@mcp.tool()
async def index_full(repo_path: str) -> dict:
    """Enqueue a full index job for the given repository path."""
    if not _producer:
        raise RuntimeError("MCP server not initialized")
    stream_id = await _producer.submit_full_index(repo_path)
    return {"status": "queued", "stream_id": stream_id, "repo_path": repo_path}


@mcp.tool()
async def index_incremental(repo_path: str, changed_paths: list[str]) -> dict:
    """Enqueue an incremental index job for a list of changed files."""
    if not _producer:
        raise RuntimeError("MCP server not initialized")
    stream_id = await _producer.submit_incremental_index(repo_path, changed_paths)
    return {
        "status": "queued",
        "stream_id": stream_id,
        "changed_count": len(changed_paths),
    }


# ---------------------------------------------------------------------------
# Read tools (sync – direct graph query)
# ---------------------------------------------------------------------------

@mcp.tool()
def find_symbol(name: str, limit: int = 20) -> list[dict]:
    """Find symbols by name or qualified name fragment."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
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


@mcp.tool()
def find_callers(qualified_name: str, limit: int = 20) -> list[dict]:
    """Return all symbols that call the given qualified name."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    result = _graph.query(
        S.QUERY_FIND_CALLERS, {"qualified_name": qualified_name, "limit": limit}
    )
    return [
        {"caller": row[0], "file_path": row[1], "line_start": row[2]}
        for row in result.result_set
    ]


@mcp.tool()
def find_callees(qualified_name: str, limit: int = 20) -> list[dict]:
    """Return all symbols called by the given qualified name."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
    result = _graph.query(
        S.QUERY_FIND_CALLEES, {"qualified_name": qualified_name, "limit": limit}
    )
    return [
        {"callee": row[0], "file_path": row[1], "line_start": row[2]}
        for row in result.result_set
    ]


@mcp.tool()
def retrieve_context(query: str, limit: int = 10) -> list[dict]:
    """Retrieve relevant code context for an agent query string."""
    if not _graph:
        raise RuntimeError("MCP server not initialized")
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
