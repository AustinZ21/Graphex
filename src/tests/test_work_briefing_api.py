from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import backend.main as main_module
from backend.auth.dependencies import require_admin
from backend.main import app
from backend.workbriefing.service import WorkBriefingService


@pytest.mark.asyncio
async def test_admin_work_briefing_endpoint_returns_cross_project_summary(pg_activity_store, monkeypatch) -> None:
    service = WorkBriefingService(store=pg_activity_store)
    monkeypatch.setattr(main_module, "_work_briefing_service", service)

    app.dependency_overrides[require_admin] = lambda: {"role": "admin", "username": "admin"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/health")
        await service.record_activity({
            "project_id": "CGA123",
            "event_type": "review",
            "title": "Reviewed PR",
            "status": "done",
        })
        await service.record_activity({
            "project_id": "WA123",
            "event_type": "sync",
            "title": "Synced tasks",
            "status": "pending",
        })

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/work-briefing?limit=10")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["total_events"] == 2
    assert response.json()["project_counts"] == {"CGA123": 1, "WA123": 1}


@pytest.mark.asyncio
async def test_admin_work_briefing_can_request_external_enrichment(pg_activity_store, auth_pg_pool, monkeypatch) -> None:
    service = WorkBriefingService(store=pg_activity_store)
    monkeypatch.setattr(main_module, "_work_briefing_service", service)

    class FakeAzureDevOpsEnricher:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def enrich_briefing(self, payload: dict) -> dict:
            return {**payload, "external_enrichment": {"status": "ok", "provider": "azure_devops"}}

    monkeypatch.setattr(main_module, "AzureDevOpsEnricher", FakeAzureDevOpsEnricher)

    app.dependency_overrides[require_admin] = lambda: {"id": 1, "role": "admin", "username": "admin"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/health")
        await service.record_activity({
            "project_id": "CGA123",
            "event_type": "checkin",
            "title": "Linked PBI 5273",
            "tags": ["pbi:5273"],
        })

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/work-briefing?limit=10&include_external=true")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["external_enrichment"] == {"status": "ok", "provider": "azure_devops"}


@pytest.mark.asyncio
async def test_admin_work_briefing_activities_endpoint_filters_project(pg_activity_store, monkeypatch) -> None:
    service = WorkBriefingService(store=pg_activity_store)
    monkeypatch.setattr(main_module, "_work_briefing_service", service)

    app.dependency_overrides[require_admin] = lambda: {"role": "admin", "username": "admin"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.get("/health")
        await service.record_activity({
            "project_id": "CGA123",
            "event_type": "code_change",
            "title": "Merged WA",
        })
        await service.record_activity({
            "project_id": "WA123",
            "event_type": "sync",
            "title": "Synced reminders",
        })

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/work-briefing/activities?project_id=CGA123&limit=10")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "CGA123"
    assert payload["count"] == 1
    assert payload["activities"][0]["title"] == "Merged WA"
