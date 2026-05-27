from __future__ import annotations

import pytest

from backend.schedules.models import ScheduledTaskCreate, ScheduledTaskUpdate
from backend.schedules.service import (
    create_scheduled_task,
    get_due_scheduled_tasks,
    list_scheduled_tasks,
    record_scheduled_task_run,
    update_scheduled_task,
)


async def _seed_project(db, *, project_id: int = 1, project_name: str = "browseragent") -> None:
    await db.execute(
        "INSERT INTO projects(id, project_name, project_id, upstream_url, is_active) VALUES (?, ?, ?, ?, 1)",
        (project_id, project_name, "BA12345678", "http://localhost:9876"),
    )


@pytest.mark.asyncio
async def test_create_scheduled_task_persists_payload_and_due_time(auth_pg_pool) -> None:
    payload = {"action": "ping", "params": {"scope": "smoke"}}

    async with auth_pg_pool.acquire() as db:
        await _seed_project(db)
        task = await create_scheduled_task(
            db,
            ScheduledTaskCreate(
                name="Hourly browser smoke",
                task_type="browseragent_task",
                project_id=1,
                agent_id="browseragent-local",
                target_url="http://localhost:9876/command",
                cadence_minutes=15,
                payload=payload,
            ),
        )

        tasks = await list_scheduled_tasks(db)
        due = await get_due_scheduled_tasks(db, now_iso="2100-01-01T00:00:00+00:00")

    assert task.id > 0
    assert task.enabled is True
    assert task.next_run_at
    assert tasks.items[0].project_name == "browseragent"
    assert tasks.items[0].payload == payload
    assert [item.id for item in due] == [task.id]


@pytest.mark.asyncio
async def test_disabled_scheduled_task_is_not_due(auth_pg_pool) -> None:
    async with auth_pg_pool.acquire() as db:
        await _seed_project(db)
        task = await create_scheduled_task(
            db,
            ScheduledTaskCreate(
                name="Disabled activation",
                task_type="agent_activation",
                project_id=1,
                agent_id="edge-agent-a",
                target_url="http://localhost:3002/activate",
                cadence_minutes=30,
                enabled=True,
            ),
        )

        updated = await update_scheduled_task(db, task.id, ScheduledTaskUpdate(enabled=False))
        due = await get_due_scheduled_tasks(db, now_iso="2100-01-01T00:00:00+00:00")

    assert updated.enabled is False
    assert due == []


@pytest.mark.asyncio
async def test_record_scheduled_task_run_updates_task_status(auth_pg_pool) -> None:
    async with auth_pg_pool.acquire() as db:
        await _seed_project(db)
        task = await create_scheduled_task(
            db,
            ScheduledTaskCreate(
                name="BrowserAgent ping",
                task_type="browseragent_task",
                project_id=1,
                target_url="http://localhost:9876/command",
                cadence_minutes=10,
            ),
        )

        run = await record_scheduled_task_run(
            db,
            task,
            status="success",
            status_code=202,
            duration_ms=34,
            response={"queued": True},
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:01:00+00:00",
        )
        refreshed = await list_scheduled_tasks(db)

    assert run.id > 0
    assert run.schedule_id == task.id
    assert run.status == "success"
    assert refreshed.items[0].last_run_status == "success"
    assert refreshed.items[0].last_run_at
    assert refreshed.items[0].next_run_at == "2026-01-01T00:11:00+00:00"