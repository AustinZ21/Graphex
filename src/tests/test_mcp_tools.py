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


def test_find_variable_returns_results():
    mcp_srv._graph = _mock_graph(
        [["backend.service.render:label", "backend.service.render", "src/backend/service.py", 12, "local"]]
    )
    results = mcp_srv.find_variable(name="label", limit=5)
    assert len(results) == 1
    assert results[0]["qualified_name"] == "backend.service.render:label"
    assert results[0]["role"] == "local"


def test_get_variable_flows():
    mcp_srv._graph = _mock_graph(
        [["backend.service.render:input", "backend.service.render:label", "assignment", 12]]
    )
    results = mcp_srv.get_variable_flows("backend.service.render", limit=20)
    assert results[0]["source"] == "backend.service.render:input"
    assert results[0]["target"] == "backend.service.render:label"


def test_trace_variable_lineage():
    mcp_srv._graph = _mock_graph(
        [[["backend.service.render:input"] , ["backend.service.render:result"]]]
    )
    result = mcp_srv.trace_variable_lineage("backend.service.render:label")
    assert result["qualified_name"] == "backend.service.render:label"
    assert result["upstream"] == ["backend.service.render:input"]
    assert result["downstream"] == ["backend.service.render:result"]


def test_analyze_return_influence():
    mcp_srv._graph = _mock_graph(
        [
            [
                "backend.service.render:input",
                [
                    "backend.service.render:input",
                    "backend.service.render:label",
                    "backend.service.render:result",
                    "backend.service.render:__return__",
                ],
            ],
            [
                "backend.service.render:suffix",
                [
                    "backend.service.render:suffix",
                    "backend.service.render:result",
                    "backend.service.render:__return__",
                ],
            ],
        ]
    )
    result = mcp_srv.analyze_return_influence("backend.service.render", limit=10)
    assert result["scope_qname"] == "backend.service.render"
    assert result["influenced_by_parameters"] == [
        "backend.service.render:input",
        "backend.service.render:suffix",
    ]
    assert result["paths"][0]["path_length"] >= 1


def test_retrieve_context():
    mcp_srv._graph = _mock_graph(
        [["backend.indexer.parser.PythonParser.parse", "method", "src/backend/indexer/parser.py", 40, 70]]
    )
    with patch("backend.tools.server._read_symbol_snippet", return_value="def parse(...): ..."), patch(
        "backend.tools.server._fetch_relation_summary",
        return_value={
            "callers": ["caller.one"],
            "callees": ["callee.one"],
            "callers_count": 1,
            "callees_count": 1,
        },
    ):
        results = mcp_srv.retrieve_context(query="parse", limit=5)
    assert results[0]["file_path"] == "src/backend/indexer/parser.py"
    assert results[0]["snippet"] == "def parse(...): ..."
    assert "summary" in results[0]
    assert results[0]["callers"] == ["caller.one"]
    assert results[0]["callees"] == ["callee.one"]


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
        elif "Variable" in cypher:
            r.result_set = [[18]]
        elif "CALLS" in cypher:
            r.result_set = [[15]]
        elif "FLOWS_TO" in cypher:
            r.result_set = [[9]]
        else:
            r.result_set = [[0]]
        return r
    graph.query.side_effect = side_effect
    mcp_srv._graph = graph
    stats = mcp_srv.get_stats()
    assert stats["symbols"] == 42
    assert stats["files"] == 10
    assert stats["variables"] == 18
    assert stats["call_edges"] == 15
    assert stats["variable_flow_edges"] == 9


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


def test_strategy_query_uses_server_strategy():
    mcp_srv._graph = MagicMock()
    with patch("backend.tools.server.run_cg_first_strategy") as mocked:
        mocked.return_value = {
            "strategy": "cg-first",
            "source": "contextgraph-server",
            "used_fallback": False,
            "graph_context": [{"qualified_name": "pkg.mod.fn"}],
        }
        result = mcp_srv.strategy_query(query="index flow")

    assert result["strategy"] == "cg-first"
    mocked.assert_called_once()


# ---------------------------------------------------------------------------
# Aggregation & architecture analysis tools
# ---------------------------------------------------------------------------

def test_get_architecture_overview():
    mcp_srv._graph = _mock_graph([[15, 250, 2, 8, 16.7, 1.2]])
    result = mcp_srv.get_architecture_overview()
    assert result["total_files"] == 15
    assert result["total_symbols"] == 250
    assert result["languages"] == 2
    assert result["files_with_incoming_calls"] == 8
    assert result["avg_symbols_per_file"] == 16.7
    assert result["avg_callers_per_file"] == 1.2


def test_get_key_modules():
    rows = [
        ["src/main.py", "python", 12, 15, 8, 5.6],
        ["src/util.py", "python", 8, 5, 3, 2.1],
    ]
    mcp_srv._graph = _mock_graph(rows)
    result = mcp_srv.get_key_modules(limit=10)
    assert len(result) == 2
    assert result[0]["file_path"] == "src/main.py"
    assert result[0]["importance_score"] == 5.6


def test_get_file_stats():
    mcp_srv._graph = _mock_graph([[12, 5, 8]])
    result = mcp_srv.get_file_stats("src/core.py")
    assert result["file_path"] == "src/core.py"
    assert result["symbol_count"] == 12
    assert result["incoming_calls"] == 5
    assert result["symbols_with_outgoing_calls"] == 8


def test_analyze_dependencies():
    rows = [
        ["src/main.py", "src/util.py", 3, 2],
        ["src/core.py", "src/main.py", 2, 4],
    ]
    mcp_srv._graph = _mock_graph(rows)
    result = mcp_srv.analyze_dependencies(limit=20)
    assert len(result) == 2
    assert result[0]["from_file"] == "src/main.py"
    assert result[0]["caller_symbols"] == 3


def test_find_dependency_chain():
    rows = [[2, 5], [3, 2]]
    mcp_srv._graph = _mock_graph(rows)
    result = mcp_srv.find_dependency_chain("src/a.py", "src/b.py")
    assert result["source_path"] == "src/a.py"
    assert result["target_path"] == "src/b.py"
    assert result["closest_distance"] == 2
    assert len(result["chains"]) == 2


def test_find_dependency_chain_no_path():
    mcp_srv._graph = _mock_graph([])
    result = mcp_srv.find_dependency_chain("src/x.py", "src/y.py")
    assert result["closest_distance"] is None
    assert result["chains"] == []


# ---------------------------------------------------------------------------
# Import tracking tools
# ---------------------------------------------------------------------------

def test_get_file_imports():
    rows = [["src/utils.py", "python"], ["src/helpers.py", "python"]]
    mcp_srv._graph = _mock_graph(rows)
    result = mcp_srv.get_file_imports("src/main.py")
    assert len(result) == 2
    assert result[0]["target_file"] == "src/utils.py"


def test_get_file_dependents():
    rows = [["src/handler.py", "python"], ["src/service.py", "python"]]
    mcp_srv._graph = _mock_graph(rows)
    result = mcp_srv.get_file_dependents("src/core.py")
    assert len(result) == 2
    assert result[0]["dependent_file"] == "src/handler.py"


def test_get_dependency_overview():
    rows = [
        ["src/main.py", "src/utils.py", "python", "python"],
        ["src/main.py", "src/helpers.py", "python", "python"],
        ["src/app.ts", "src/utils.ts", "typescript", "typescript"],
    ]
    mcp_srv._graph = _mock_graph(rows)
    result = mcp_srv.get_dependency_overview(limit=30)
    assert len(result) == 3
    assert result[0]["from_file"] == "src/main.py"


def test_analyze_import_surface():
    rows = [
        ["src/core.py", "python", 5, 8],
        ["src/utils.py", "python", 2, 3],
    ]
    mcp_srv._graph = _mock_graph(rows)
    result = mcp_srv.analyze_import_surface(limit=15)
    assert len(result) == 2
    assert result[0]["file_path"] == "src/core.py"
    assert result[0]["internal_imports"] == 5
    assert result[0]["incoming_imports"] == 8

