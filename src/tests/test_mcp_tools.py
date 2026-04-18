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
    mcp_srv._cache = None
    mcp_srv._recorder = None
    yield
    mcp_srv._graph = None
    mcp_srv._producer = None
    mcp_srv._cache = None
    mcp_srv._recorder = None


def _mock_graph(rows: list[list]) -> MagicMock:
    graph = MagicMock()
    result = MagicMock()
    result.result_set = rows
    graph.query.return_value = result
    return graph


def _mock_producer(stream_id: str = "1234-0") -> AsyncMock:
    producer = AsyncMock()
    producer.submit_full_index.return_value = {"job_id": "job-1", "stream_id": stream_id}
    producer.submit_incremental_index.return_value = {"job_id": "job-2", "stream_id": stream_id}
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
    results = mcp_srv.find_symbol(name="PythonParser", limit=5)
    assert len(results) == 1
    assert results[0]["qualified_name"] == "backend.indexer.parser.PythonParser"
    assert results[0]["symbol_type"] == "class"


def test_find_symbol_not_initialized():
    with pytest.raises(RuntimeError, match="not initialized"):
        mcp_srv.find_symbol(name="anything")


def test_find_callers():
    mcp_srv._graph = _mock_graph(
        [["backend.main.lifespan", "src/backend/main.py", 42]]
    )
    results = mcp_srv.find_callers(qualified_name="backend.graph.client.GraphClient.connect")
    assert results[0]["caller"] == "backend.main.lifespan"


def test_find_callees():
    mcp_srv._graph = _mock_graph(
        [["backend.graph.client.GraphClient.query", "src/backend/graph/client.py", 44]]
    )
    results = mcp_srv.find_callees(qualified_name="backend.indexer.pipeline.IndexPipeline._index_file")
    assert "callee" in results[0]


def test_retrieve_context():
    mcp_srv._graph = _mock_graph(
        [["backend.indexer.parser.PythonParser.parse", "method", "src/backend/indexer/parser.py", 40, 70]]
    )
    results = mcp_srv.retrieve_context(query="parse", limit=5)
    assert results[0]["file_path"] == "src/backend/indexer/parser.py"


@pytest.mark.asyncio
async def test_index_full_queues_job():
    mcp_srv._producer = _mock_producer("5000-0")
    result = await mcp_srv.index_full(repo_path="/repo/myproject")
    assert result["status"] == "queued"
    assert result["stream_id"] == "5000-0"
    assert result["job_id"] == "job-1"
    mcp_srv._producer.submit_full_index.assert_awaited_once_with("/repo/myproject")


@pytest.mark.asyncio
async def test_index_incremental_queues_job():
    mcp_srv._producer = _mock_producer("5001-0")
    result = await mcp_srv.index_incremental(
        repo_path="/repo", changed_paths=["a.py", "b.py"]
    )
    assert result["changed_count"] == 2
    assert result["job_id"] == "job-2"
    mcp_srv._producer.submit_incremental_index.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_index_job_status():
    producer = _mock_producer("5002-0")
    producer.get_job_status.return_value = {"job_id": "job-2", "status": "processing"}
    mcp_srv._producer = producer

    result = await mcp_srv.get_index_job_status("job-2")
    assert result["status"] == "processing"
    producer.get_job_status.assert_awaited_once_with("job-2")


@pytest.mark.asyncio
async def test_wait_for_index_ready():
    producer = _mock_producer("5003-0")
    producer.wait_for_job_status.return_value = {
        "job_id": "job-3",
        "status": "done",
        "ready": True,
        "timeout": False,
    }
    mcp_srv._producer = producer

    result = await mcp_srv.wait_for_index_ready("job-3", timeout_sec=5.0, poll_interval_sec=0.2)
    assert result["ready"] is True
    producer.wait_for_job_status.assert_awaited_once_with(
        "job-3",
        timeout_sec=5.0,
        poll_interval_sec=0.2,
    )


@pytest.mark.asyncio
async def test_index_full_not_initialized():
    with pytest.raises(RuntimeError, match="not initialized"):
        await mcp_srv.index_full(repo_path="/repo")


# ---------------------------------------------------------------------------
# Phase 2 tools
# ---------------------------------------------------------------------------

def test_find_call_graph():
    graph = MagicMock()
    callers_result = MagicMock()
    callers_result.result_set = [["backend.main.lifespan"]]
    callees_result = MagicMock()
    callees_result.result_set = [["backend.graph.client.GraphClient.connect"]]
    graph.query.side_effect = [callers_result, callees_result]
    mcp_srv._graph = graph
    result = mcp_srv.find_call_graph(qualified_name="backend.indexer.pipeline.IndexPipeline._upsert_repo")
    assert "callers" in result
    assert "callees" in result


def test_get_stats():
    graph = MagicMock()
    def side_effect(cypher, *args, **kwargs):
        r = MagicMock()
        if "Symbol" in cypher:
            r.result_set = [[42]]
        elif "File" in cypher:
            r.result_set = [[10]]
        elif "CALLS" in cypher:
            r.result_set = [[15]]
        else:
            r.result_set = [[0]]
        return r
    graph.query.side_effect = side_effect
    mcp_srv._graph = graph
    stats = mcp_srv.get_stats()
    assert stats["symbols"] == 42
    assert stats["files"] == 10
    assert stats["call_edges"] == 15


# ---------------------------------------------------------------------------
# Phase 3 tools
# ---------------------------------------------------------------------------

def test_clear_cache_no_cache():
    result = mcp_srv.clear_cache()
    assert result["status"] == "no_cache_configured"


def test_clear_cache_with_cache():
    mock_cache = MagicMock()
    mock_cache.invalidate_all.return_value = 5
    mcp_srv._cache = mock_cache
    result = mcp_srv.clear_cache()
    assert result["deleted"] == 5
    assert result["status"] == "ok"

