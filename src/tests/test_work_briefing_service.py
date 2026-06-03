from __future__ import annotations

import pytest

from backend.workbriefing.service import WorkActivityValidationError, WorkBriefingService


@pytest.mark.asyncio
async def test_record_activity_persists_and_updates_by_external_id(pg_activity_store) -> None:
    service = WorkBriefingService(store=pg_activity_store)

    created = await service.record_activity(
        {
            "project_id": "CGA123",
            "workspace_name": "Context Graph Agent",
            "event_type": "code_change",
            "external_id": "pr-42",
            "title": "Integrate WA",
            "summary": "ported activity store",
            "status": "in_progress",
            "tags": ["merge", "wa"],
        }
    )
    updated = await service.record_activity(
        {
            "project_id": "CGA123",
            "workspace_name": "Context Graph Agent",
            "event_type": "code_change",
            "external_id": "pr-42",
            "title": "Integrate WA",
            "summary": "added admin briefing",
            "status": "done",
            "tags": ["merge", "briefing"],
        }
    )
    rows = await service.list_recent(project_id="CGA123")

    assert created.operation == "created"
    assert updated.operation == "updated"
    assert created.activity.activity_id == updated.activity.activity_id
    assert len(rows) == 1
    assert rows[0].summary == "added admin briefing"
    assert rows[0].status == "done"
    assert rows[0].tags == ("merge", "briefing")


@pytest.mark.asyncio
async def test_get_briefing_aggregates_projects_and_statuses(pg_activity_store) -> None:
    service = WorkBriefingService(store=pg_activity_store)

    await service.record_activity(
        {
            "project_id": "CGA123",
            "event_type": "review",
            "title": "Reviewed PR",
            "status": "done",
        }
    )
    await service.record_activity(
        {
            "project_id": "WA123",
            "event_type": "sync",
            "title": "Synced tickets",
            "status": "pending",
        }
    )

    briefing = await service.get_briefing(limit=10)

    assert briefing["total_events"] == 2
    assert briefing["event_type_counts"] == {"review": 1, "sync": 1}
    assert briefing["status_counts"] == {"done": 1, "pending": 1}
    assert briefing["project_counts"] == {"CGA123": 1, "WA123": 1}


@pytest.mark.asyncio
async def test_record_activity_rejects_missing_required_fields(pg_activity_store) -> None:
    service = WorkBriefingService(store=pg_activity_store)

    with pytest.raises(WorkActivityValidationError):
        await service.record_activity({"project_id": "CGA123", "event_type": "sync"})
