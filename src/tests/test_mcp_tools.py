"""Unit tests for MCP tool handlers using mocked graph and producer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import backend.tools.server as mcp_srv


@pytest.fixture(autouse=True)
def reset_server_state():
    """Reset module-level singletons between tests."""
    mcp_srv._graph = None
    mcp_srv._producer = None
    yield
    mcp_srv._graph = None
    mcp_srv._producer = None


def _mock_graph(rows: list[list]) -> MagicMock:
    graph = MagicMock()
    result = MagicMock()
    result.result_set = rows
    graph.query.return_value = result
    return graph


def _mock_producer(stream_id: str = "1234-0") -> AsyncMock:
    producer = AsyncMock()
    producer.submit_full_index.return_value = stream_id
    producer.submit_incremental_index.return_value = stream_id
    return producer


def test_init_sets_singletons():
    graph = MagicMock()
    producer = MagicMock()
    mcp_srv.init(graph=graph, producer=producer)
    assert mcp_srv._graph is graph
    assert mcp_srv._producer is producer


def test_find_symbol_returns_results():
    mcp_srv._graph = _mock_graph(
        [["backend.indexer.parser.PythonParser", "class", "src/backend/indexer/parser.py", 30, 80]]
    )
    results = mcp_srv.find_symbol.fn(name="PythonParser", limit=5)
    assert len(results) == 1
    assert results[0]["qualified_name"] == "backend.indexer.parser.PythonParser"
    assert results[0]["symbol_type"] == "class"


def test_find_symbol_not_initialized():
    with pytest.raises(RuntimeError, match="not initialized"):
        mcp_srv.find_symbol.fn(name="anything")


def test_find_callers():
    mcp_srv._graph = _mock_graph(
        [["backend.main.lifespan", "src/backend/main.py", 42]]
    )
    results = mcp_srv.find_callers.fn(qualified_name="backend.graph.client.GraphClient.connect")
    assert results[0]["caller"] == "backend.main.lifespan"


def test_find_callees():
    mcp_srv._graph = _mock_graph(
        [["backend.graph.client.GraphClient.query", "src/backend/graph/client.py", 44]]
    )
    results = mcp_srv.find_callees.fn(qualified_name="backend.indexer.pipeline.IndexPipeline._index_file")
    assert "callee" in results[0]


def test_retrieve_context():
    mcp_srv._graph = _mock_graph(
        [["backend.indexer.parser.PythonParser.parse", "method", "src/backend/indexer/parser.py", 40, 70]]
    )
    results = mcp_srv.retrieve_context.fn(query="parse", limit=5)
    assert results[0]["file_path"] == "src/backend/indexer/parser.py"


@pytest.mark.asyncio
async def test_index_full_queues_job():
    mcp_srv._producer = _mock_producer("5000-0")
    result = await mcp_srv.index_full.fn(repo_path="/repo/myproject")
    assert result["status"] == "queued"
    assert result["stream_id"] == "5000-0"
    mcp_srv._producer.submit_full_index.assert_awaited_once_with("/repo/myproject")


@pytest.mark.asyncio
async def test_index_incremental_queues_job():
    mcp_srv._producer = _mock_producer("5001-0")
    result = await mcp_srv.index_incremental.fn(
        repo_path="/repo", changed_paths=["a.py", "b.py"]
    )
    assert result["changed_count"] == 2
    mcp_srv._producer.submit_incremental_index.assert_awaited_once()


@pytest.mark.asyncio
async def test_index_full_not_initialized():
    with pytest.raises(RuntimeError, match="not initialized"):
        await mcp_srv.index_full.fn(repo_path="/repo")
