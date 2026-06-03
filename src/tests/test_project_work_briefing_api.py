from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import backend.main as main_module
from backend.auth.security import hash_token
from backend.main import app
from backend.workbriefing.service import WorkBriefingService
from backend.workbriefing.store import PgVectorActivityStore


async def _seed_project_auth(pool) -> None:
    async with pool.acquire() as db:
        await db.execute(
            "INSERT INTO projects(id, project_name, project_id, upstream_url, "
            "description, repo_path, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)",
            (
                1,
                "contextgraphagent",
                "CGA123",
                "http://localhost:18001",
                "CGA host project",
                "D:/Repos/Context Graph Agent",
            ),
        )
        await db.execute(
            "INSERT INTO project_tokens(project_id, token_type, token_hash, "
            "token_hint, version, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            (1, "edge_agent", hash_token("edge-token"), "edge-tok", 1),
        )
        await db.execute(
            "INSERT INTO project_tokens(project_id, token_type, token_hash, "
            "token_hint, version, is_active) VALUES (?, ?, ?, ?, ?, 1)",
            (1, "mcp", hash_token("mcp-token"), "mcp-tokn", 1),
        )


def _install_service(monkeypatch, pg_store: PgVectorActivityStore) -> None:
    service = WorkBriefingService(store=pg_store)
    monkeypatch.setattr(main_module, "_work_briefing_service", service)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_project_api_records_activity_with_edge_agent_token(
    monkeypatch, auth_pg_pool, pg_activity_store
) -> None:
    await _seed_project_auth(auth_pg_pool)
    _install_service(monkeypatch, pg_activity_store)

    async with _client() as client:
        response = await client.post(
            "/api/project/work-briefing/activity",
            headers={"Authorization": "Bearer edge-token"},
            json={
                "event_type": "sync",
                "title": "Synced project status",
                "summary": "pushed current repo progress to CGA",
                "status": "done",
                "tags": ["wa", "sync"],
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["operation"] == "created"
    assert payload["activity"]["project_id"] == "CGA123"
    assert payload["activity"]["workspace_name"] == "contextgraphagent"
    assert payload["activity"]["status"] == "done"


@pytest.mark.asyncio
async def test_project_api_rejects_body_project_spoof(
    monkeypatch, auth_pg_pool, pg_activity_store
) -> None:
    await _seed_project_auth(auth_pg_pool)
    _install_service(monkeypatch, pg_activity_store)

    async with _client() as client:
        response = await client.post(
            "/api/project/work-briefing/activity",
            headers={"Authorization": "Bearer mcp-token"},
            json={
                "project_id": "WA999",
                "event_type": "sync",
                "title": "Attempted spoof",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "project_id must match the authenticated project"


@pytest.mark.asyncio
async def test_project_api_summary_uses_authenticated_project_scope(
    monkeypatch, auth_pg_pool, pg_activity_store
) -> None:
    await _seed_project_auth(auth_pg_pool)
    _install_service(monkeypatch, pg_activity_store)

    async with _client() as client:
        create_response = await client.post(
            "/api/project/work-briefing/activity",
            headers={"Authorization": "Bearer edge-token"},
            json={
                "event_type": "review",
                "title": "Reviewed integration slice",
                "summary": "validated project-scoped ingestion",
            },
        )
        assert create_response.status_code == 201

        response = await client.get(
            "/api/project/work-briefing?limit=10",
            headers={"Authorization": "Bearer mcp-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "CGA123"
    assert payload["total_events"] == 1
    assert payload["project_counts"] == {"CGA123": 1}


@pytest.mark.asyncio
async def test_project_api_records_activity_with_ado_pbi_and_pr_refs(
    monkeypatch, auth_pg_pool, pg_activity_store
) -> None:
    """Optional but recommended: cite the ADO PBI and the repo PR via external_id /
    source_url / metadata so downstream briefings can backtrack to the originating
    work item and code change."""
    await _seed_project_auth(auth_pg_pool)
    _install_service(monkeypatch, pg_activity_store)

    async with _client() as client:
        response = await client.post(
            "/api/project/work-briefing/activity",
            headers={"Authorization": "Bearer edge-token"},
            json={
                "event_type": "checkin",
                "title": "Implemented work-briefing PBI/PR linkage example",
                "summary": "Added a test that demonstrates citing ADO PBI 123456 and GitHub PR #789.",
                "status": "done",
                "tags": ["wa", "checkin", "pbi:123456", "pr:789"],
                "external_id": "ado:pbi:123456",
                "source_url": "https://dev.azure.com/contoso/CGA/_workitems/edit/123456",
                "metadata": {
                    "ado": {
                        "organization": "contoso",
                        "project": "CGA",
                        "work_item_type": "Product Backlog Item",
                        "pbi_id": 123456,
                        "url": "https://dev.azure.com/contoso/CGA/_workitems/edit/123456",
                    },
                    "pr": {
                        "repo": "nascousa/cga",
                        "number": 789,
                        "url": "https://github.com/nascousa/cga/pull/789",
                        "branch": "feature/workbriefing-pbi-pr-example",
                        "commit": "abc1234",
                    },
                },
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["operation"] == "created"
    activity = payload["activity"]
    assert activity["project_id"] == "CGA123"
    assert activity["source_url"].endswith("/_workitems/edit/123456")
    assert activity["source_item_id"] == "ado:pbi:123456"
    assert activity["raw_metadata"]["ado"]["pbi_id"] == 123456
    assert activity["raw_metadata"]["pr"]["number"] == 789
    assert "pbi:123456" in activity["tags"]
    assert "pr:789" in activity["tags"]
