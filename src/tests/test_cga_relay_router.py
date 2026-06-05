from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.cga_relay import router as cga_relay_router


@pytest.mark.asyncio
async def test_dispatch_query_impact_graph_uses_strategy_query(monkeypatch):
    captured = {}

    def fake_strategy_query(**kwargs):
        captured.update(kwargs)
        return {"answer": "ok"}

    monkeypatch.setattr(cga_relay_router.mcp_server, "strategy_query", fake_strategy_query)

    result = await cga_relay_router.dispatch_tool(
        "query_impact_graph",
        {"query": "scanner", "token_budget": 900},
        project_name="demo",
    )

    assert result == {
        "ok": True,
        "tool": "query_impact_graph",
        "backend_tool": "strategy_query",
        "result": {"answer": "ok"},
    }
    assert captured["query"] == "scanner"
    assert captured["token_budget"] == 900


@pytest.mark.asyncio
async def test_dispatch_query_impact_graph_omits_token_budget_for_config_default(monkeypatch):
    captured = {}

    def fake_strategy_query(**kwargs):
        captured.update(kwargs)
        return {"answer": "ok"}

    monkeypatch.setattr(cga_relay_router.mcp_server, "strategy_query", fake_strategy_query)

    await cga_relay_router.dispatch_tool(
        "query_impact_graph",
        {"query": "scanner"},
        project_name="demo",
    )

    assert captured["query"] == "scanner"
    assert captured["token_budget"] is None


@pytest.mark.asyncio
async def test_dispatch_index_incremental_sets_project_name(monkeypatch):
    producer_result = {"status": "queued", "job_id": "job-1"}
    index_incremental = AsyncMock(return_value=producer_result)
    monkeypatch.setattr(cga_relay_router.mcp_server, "index_incremental", index_incremental)

    result = await cga_relay_router.dispatch_tool(
        "index_incremental",
        {"repo_path": "C:/repo", "changed_paths": ["a.py"]},
        project_name="demo",
    )

    assert result["result"] == producer_result
    index_incremental.assert_awaited_once_with(
        repo_path="C:/repo",
        changed_paths=["a.py"],
        project_name="demo",
    )


def test_require_project_match_rejects_mismatched_project_id():
    with pytest.raises(HTTPException) as exc:
        cga_relay_router._require_project_match("PROJECT123", "OTHER")

    assert exc.value.status_code == 403


def test_sync_summary_never_includes_snapshot_content():
    payload = cga_relay_router.CgaRelaySync(
        agent_id="dev-agent-01",
        project_id="PROJECT123",
        namespace="dev",
        project_tag="repo",
        root="C:/repo",
        counts={"changed": 1},
        snapshots=[{"path": "a.py", "content": "TEST_SECRET_VALUE_SHOULD_NEVER_LEAK"}],
        tombstones=["old.py"],
    )

    summary = cga_relay_router.sync_summary(payload)

    assert summary == {
        "agent_id": "dev-agent-01",
        "project_id": "PROJECT123",
        "namespace": "dev",
        "project_tag": "repo",
        "root": "C:/repo",
        "counts": {"changed": 1},
        "snapshot_count": 1,
        "tombstone_count": 1,
    }
    assert "TEST_SECRET_VALUE_SHOULD_NEVER_LEAK" not in repr(summary)


class _FakeCursor:
    def __init__(self, row):
        self.row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def fetchone(self):
        return self.row


class _FakeDb:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return _FakeCursor(self.row)


@pytest.mark.asyncio
async def test_account_project_context_resolves_active_project_by_project_id():
    db = _FakeDb({"id": 7, "project_name": "Demo", "project_id": "PROJECT123"})

    context = await cga_relay_router._account_project_context(db, "PROJECT123", {"role": "admin"})

    assert context == {
        "project_id": "PROJECT123",
        "project_name": "Demo",
        "project_db_id": 7,
    }
    assert db.calls[0][1] == ("PROJECT123",)


@pytest.mark.asyncio
async def test_account_project_context_rejects_unknown_project():
    db = _FakeDb(None)

    with pytest.raises(HTTPException) as exc:
        await cga_relay_router._account_project_context(db, "MISSING", {"role": "admin"})

    assert exc.value.status_code == 404
