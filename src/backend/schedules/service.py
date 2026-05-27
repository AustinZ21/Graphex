"""Persistence and execution service for admin scheduled automation."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from backend.auth.pgshim import Connection, get_pool
from backend.schedules.models import (
    ScheduledTaskCreate,
    ScheduledTaskList,
    ScheduledTaskOut,
    ScheduledTaskRunOut,
    ScheduledTaskUpdate,
)

log = structlog.get_logger()

TASK_SELECT = """
SELECT
    st.id,
    st.name,
    st.description,
    st.task_type,
    st.project_id,
    p.project_name,
    p.project_id AS project_external_id,
    st.agent_id,
    st.target_url,
    st.payload_json,
    st.cadence_minutes,
    st.timeout_seconds,
    st.enabled,
    st.created_at,
    st.updated_at,
    st.next_run_at,
    st.last_run_at,
    st.last_run_status,
    st.last_run_error
FROM scheduled_tasks st
LEFT JOIN projects p ON p.id = st.project_id
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    dt = value or utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def next_run_iso(cadence_minutes: int, *, from_time: datetime | None = None) -> str:
    base = from_time or utc_now()
    return iso_utc(base + timedelta(minutes=max(1, int(cadence_minutes))))


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _decode_json(value: str | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if not value:
        return dict(fallback or {})
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else dict(fallback or {})
    except Exception:
        return dict(fallback or {})


def _encode_json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, sort_keys=True, ensure_ascii=True)


def _task_from_row(row) -> ScheduledTaskOut:
    data = dict(row)
    data["payload"] = _decode_json(data.pop("payload_json", "{}"))
    data["enabled"] = bool(data.get("enabled"))
    return ScheduledTaskOut(**data)


def _run_from_row(row) -> ScheduledTaskRunOut:
    data = dict(row)
    data["response"] = _decode_json(data.pop("response_json", "{}"))
    return ScheduledTaskRunOut(**data)


async def get_scheduled_task(db: Connection, task_id: int) -> ScheduledTaskOut | None:
    async with db.execute(TASK_SELECT + " WHERE st.id = ?", (task_id,)) as cur:
        row = await cur.fetchone()
    return _task_from_row(row) if row else None


async def list_recent_scheduled_task_runs(db: Connection, *, limit: int = 25) -> list[ScheduledTaskRunOut]:
    async with db.execute(
        """
        SELECT id, schedule_id, started_at, finished_at, status, status_code, duration_ms, error, response_json
        FROM scheduled_task_runs
        ORDER BY started_at DESC, id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 200)),),
    ) as cur:
        rows = await cur.fetchall()
    return [_run_from_row(row) for row in rows]


async def list_scheduled_tasks(db: Connection, *, include_runs: bool = True) -> ScheduledTaskList:
    async with db.execute(
        TASK_SELECT + " ORDER BY st.enabled DESC, st.next_run_at ASC, st.id ASC"
    ) as cur:
        rows = await cur.fetchall()
    recent_runs = await list_recent_scheduled_task_runs(db) if include_runs else []
    return ScheduledTaskList(items=[_task_from_row(row) for row in rows], recent_runs=recent_runs)


async def create_scheduled_task(db: Connection, body: ScheduledTaskCreate) -> ScheduledTaskOut:
    now = utc_now()
    async with db.execute(
        """
        INSERT INTO scheduled_tasks(
            name, description, task_type, project_id, agent_id, target_url, payload_json,
            cadence_minutes, timeout_seconds, enabled, created_at, updated_at, next_run_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        RETURNING id
        """,
        (
            body.name,
            body.description,
            body.task_type,
            body.project_id,
            body.agent_id,
            body.target_url,
            _encode_json(body.payload),
            body.cadence_minutes,
            body.timeout_seconds,
            1 if body.enabled else 0,
            iso_utc(now),
            iso_utc(now),
            next_run_iso(body.cadence_minutes, from_time=now),
        ),
    ) as cur:
        row = await cur.fetchone()
    await db.commit()
    created = await get_scheduled_task(db, int(row["id"]))
    if created is None:
        raise RuntimeError("scheduled task insert did not return a retrievable row")
    return created


async def update_scheduled_task(db: Connection, task_id: int, body: ScheduledTaskUpdate) -> ScheduledTaskOut:
    current = await get_scheduled_task(db, task_id)
    if current is None:
        raise KeyError("Scheduled task not found")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return current

    merged = current.model_dump()
    merged.update(changes)
    candidate = ScheduledTaskCreate(
        name=merged["name"],
        description=merged.get("description") or "",
        task_type=merged["task_type"],
        project_id=merged.get("project_id"),
        agent_id=merged.get("agent_id") or "",
        target_url=merged.get("target_url") or "",
        payload=merged.get("payload") or {},
        cadence_minutes=merged["cadence_minutes"],
        timeout_seconds=merged["timeout_seconds"],
        enabled=merged["enabled"],
    )

    now = utc_now()
    recompute_next = any(key in changes for key in ("cadence_minutes", "enabled")) and candidate.enabled
    next_run_at = next_run_iso(candidate.cadence_minutes, from_time=now) if recompute_next else current.next_run_at
    await db.execute(
        """
        UPDATE scheduled_tasks
        SET name = ?, description = ?, task_type = ?, project_id = ?, agent_id = ?, target_url = ?,
            payload_json = ?, cadence_minutes = ?, timeout_seconds = ?, enabled = ?, updated_at = ?, next_run_at = ?
        WHERE id = ?
        """,
        (
            candidate.name,
            candidate.description,
            candidate.task_type,
            candidate.project_id,
            candidate.agent_id,
            candidate.target_url,
            _encode_json(candidate.payload),
            candidate.cadence_minutes,
            candidate.timeout_seconds,
            1 if candidate.enabled else 0,
            iso_utc(now),
            next_run_at,
            task_id,
        ),
    )
    await db.commit()
    updated = await get_scheduled_task(db, task_id)
    if updated is None:
        raise KeyError("Scheduled task not found")
    return updated


async def delete_scheduled_task(db: Connection, task_id: int) -> None:
    await db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
    await db.commit()


async def get_due_scheduled_tasks(
    db: Connection,
    *,
    now_iso: str | None = None,
    limit: int = 10,
) -> list[ScheduledTaskOut]:
    async with db.execute(
        TASK_SELECT
        + " WHERE st.enabled = 1 AND st.next_run_at <= ? ORDER BY st.next_run_at ASC, st.id ASC LIMIT ?",
        (now_iso or iso_utc(), max(1, min(int(limit), 50))),
    ) as cur:
        rows = await cur.fetchall()
    return [_task_from_row(row) for row in rows]


async def record_scheduled_task_run(
    db: Connection,
    task: ScheduledTaskOut,
    *,
    status: str,
    status_code: int | None = None,
    duration_ms: int = 0,
    response: dict[str, Any] | None = None,
    error: str = "",
    started_at: str | None = None,
    finished_at: str | None = None,
) -> ScheduledTaskRunOut:
    started = started_at or iso_utc()
    finished = finished_at or iso_utc()
    async with db.execute(
        """
        INSERT INTO scheduled_task_runs(
            schedule_id, started_at, finished_at, status, status_code, duration_ms, error, response_json
        ) VALUES(?,?,?,?,?,?,?,?)
        RETURNING id, schedule_id, started_at, finished_at, status, status_code, duration_ms, error, response_json
        """,
        (
            task.id,
            started,
            finished,
            status,
            status_code,
            max(0, int(duration_ms)),
            error[:1000],
            _encode_json(response),
        ),
    ) as cur:
        row = await cur.fetchone()

    await db.execute(
        """
        UPDATE scheduled_tasks
        SET last_run_at = ?, last_run_status = ?, last_run_error = ?, next_run_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            finished,
            status,
            error[:1000],
            next_run_iso(task.cadence_minutes, from_time=parse_iso_utc(finished)),
            finished,
            task.id,
        ),
    )
    await db.commit()
    return _run_from_row(row)


def build_request_payload(task: ScheduledTaskOut) -> dict[str, Any]:
    if task.task_type == "agent_activation":
        return {
            "action": "activate_agent",
            "agent_id": task.agent_id,
            "project_id": task.project_external_id,
            "payload": task.payload,
        }
    return dict(task.payload or {})


async def execute_scheduled_task(db: Connection, task: ScheduledTaskOut) -> ScheduledTaskRunOut:
    started_at = iso_utc()
    started_clock = time.perf_counter()
    if not task.target_url:
        return await record_scheduled_task_run(
            db,
            task,
            status="failed",
            duration_ms=0,
            error="target_url is required",
            started_at=started_at,
        )

    try:
        async with httpx.AsyncClient(timeout=float(task.timeout_seconds)) as client:
            response = await client.post(task.target_url, json=build_request_payload(task))
        duration_ms = int((time.perf_counter() - started_clock) * 1000)
        try:
            response_payload: dict[str, Any] = response.json() if response.content else {}
            if not isinstance(response_payload, dict):
                response_payload = {"body": response_payload}
        except Exception:
            response_payload = {"body": response.text[:2000]}
        status = "success" if response.status_code < 400 else "failed"
        error = "" if status == "success" else response.text[:1000]
        return await record_scheduled_task_run(
            db,
            task,
            status=status,
            status_code=response.status_code,
            duration_ms=duration_ms,
            response=response_payload,
            error=error,
            started_at=started_at,
            finished_at=iso_utc(),
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_clock) * 1000)
        return await record_scheduled_task_run(
            db,
            task,
            status="failed",
            duration_ms=duration_ms,
            error=str(exc),
            started_at=started_at,
            finished_at=iso_utc(),
        )


class ScheduledTaskWorker:
    def __init__(self, *, poll_seconds: float = 30.0, batch_size: int = 10) -> None:
        self.poll_seconds = max(5.0, float(poll_seconds))
        self.batch_size = max(1, int(batch_size))
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="cga-scheduled-task-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def run_due_once(self) -> int:
        pool = get_pool()
        async with pool.acquire() as db:
            due = await get_due_scheduled_tasks(db, limit=self.batch_size)
            for task in due:
                await execute_scheduled_task(db, task)
            return len(due)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                count = await self.run_due_once()
                if count:
                    log.info("schedules.ran_due_tasks", count=count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("schedules.worker_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
