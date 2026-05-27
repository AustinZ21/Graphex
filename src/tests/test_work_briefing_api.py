from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import backend.main as main_module
from backend.auth.dependencies import require_admin
from backend.main import app
from backend.workbriefing.service import WorkBriefingService


def test_admin_work_briefing_endpoint_returns_cross_project_summary(pg_activity_store, monkeypatch) -> None:
    service = WorkBriefingService(store=pg_activity_store)
    monkeypatch.setattr(main_module, "_work_briefing_service", service)

    client = TestClient(app)
    app.dependency_overrides[require_admin] = lambda: {"role": "admin", "username": "admin"}
    try:
        client.get("/health")
        asyncio.run(service.record_activity({
            "project_id": "CGA123",
            "event_type": "review",
            "title": "Reviewed PR",
            "status": "done",
        }))
        asyncio.run(service.record_activity({
            "project_id": "WA123",
            "event_type": "sync",
            "title": "Synced tasks",
            "status": "pending",
        }))

        response = client.get("/api/admin/work-briefing?limit=10")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["total_events"] == 2
    assert response.json()["project_counts"] == {"CGA123": 1, "WA123": 1}


def test_admin_work_briefing_activities_endpoint_filters_project(pg_activity_store, monkeypatch) -> None:
    service = WorkBriefingService(store=pg_activity_store)
    monkeypatch.setattr(main_module, "_work_briefing_service", service)

    client = TestClient(app)
    app.dependency_overrides[require_admin] = lambda: {"role": "admin", "username": "admin"}
    try:
        client.get("/health")
        asyncio.run(service.record_activity({
            "project_id": "CGA123",
            "event_type": "code_change",
            "title": "Merged WA",
        }))
        asyncio.run(service.record_activity({
            "project_id": "WA123",
            "event_type": "sync",
            "title": "Synced reminders",
        }))

        response = client.get("/api/admin/work-briefing/activities?project_id=CGA123&limit=10")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "CGA123"
    assert payload["count"] == 1
    assert payload["activities"][0]["title"] == "Merged WA"
