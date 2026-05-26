from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import aiosqlite

from backend.auth import database as auth_database
from backend.workbriefing.models import WorkActivity, parse_utc_datetime


@dataclass(frozen=True)
class ActivityUpsertResult:
    operation: str
    activity: WorkActivity


class ActivityStore(Protocol):
    async def upsert(self, activity: WorkActivity) -> ActivityUpsertResult:
        ...

    async def list_recent(self, project_id: str | None = None, limit: int = 25) -> list[WorkActivity]:
        ...


class SqliteActivityStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or auth_database.DB_PATH
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            await auth_database.init_db(self._db_path)
            self._schema_ready = True

    async def upsert(self, activity: WorkActivity) -> ActivityUpsertResult:
        await self._ensure_schema()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        key = self._key_for(activity)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT activity_id
                FROM work_activities
                WHERE plugin_id = ? AND project_id = ? AND source_type = ? AND source_item_id = ?
                """,
                key,
            ) as cursor:
                existing = await cursor.fetchone()

            persisted_activity = activity
            operation = "created"
            if existing:
                operation = "updated"
                persisted_activity = WorkActivity(
                    activity_id=str(existing["activity_id"]),
                    plugin_id=activity.plugin_id,
                    source_system=activity.source_system,
                    source_type=activity.source_type,
                    source_item_id=activity.source_item_id,
                    project_id=activity.project_id,
                    workspace_name=activity.workspace_name,
                    event_type=activity.event_type,
                    title=activity.title,
                    summary=activity.summary,
                    body_text=activity.body_text,
                    status=activity.status,
                    priority=activity.priority,
                    owner=activity.owner,
                    source_url=activity.source_url,
                    tags=activity.tags,
                    occurred_at=activity.occurred_at,
                    synced_at=activity.synced_at,
                    content_hash=activity.content_hash,
                    raw_metadata=activity.raw_metadata,
                    embedding_text=activity.embedding_text,
                )

            await db.execute(
                """
                INSERT INTO work_activities (
                    activity_id,
                    plugin_id,
                    source_system,
                    source_type,
                    source_item_id,
                    project_id,
                    workspace_name,
                    event_type,
                    title,
                    summary,
                    body_text,
                    status,
                    priority,
                    owner,
                    source_url,
                    tags_json,
                    occurred_at,
                    synced_at,
                    content_hash,
                    raw_metadata_json,
                    embedding_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(plugin_id, project_id, source_type, source_item_id)
                DO UPDATE SET
                    source_system = excluded.source_system,
                    workspace_name = excluded.workspace_name,
                    event_type = excluded.event_type,
                    title = excluded.title,
                    summary = excluded.summary,
                    body_text = excluded.body_text,
                    status = excluded.status,
                    priority = excluded.priority,
                    owner = excluded.owner,
                    source_url = excluded.source_url,
                    tags_json = excluded.tags_json,
                    occurred_at = excluded.occurred_at,
                    synced_at = excluded.synced_at,
                    content_hash = excluded.content_hash,
                    raw_metadata_json = excluded.raw_metadata_json,
                    embedding_text = excluded.embedding_text
                """,
                self._row_for(persisted_activity),
            )
            await db.commit()

        return ActivityUpsertResult(operation=operation, activity=persisted_activity)

    async def list_recent(self, project_id: str | None = None, limit: int = 25) -> list[WorkActivity]:
        await self._ensure_schema()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        safe_limit = max(1, min(limit, 100))
        query = """
            SELECT
                activity_id,
                plugin_id,
                source_system,
                source_type,
                source_item_id,
                project_id,
                workspace_name,
                event_type,
                title,
                summary,
                body_text,
                status,
                priority,
                owner,
                source_url,
                tags_json,
                occurred_at,
                synced_at,
                content_hash,
                raw_metadata_json,
                embedding_text
            FROM work_activities
        """
        params: list[object] = []
        if project_id:
            query += " WHERE project_id = ?"
            params.append(project_id)
        query += " ORDER BY occurred_at DESC, synced_at DESC, source_item_id DESC LIMIT ?"
        params.append(safe_limit)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
        return [self._activity_from_row(row) for row in rows]

    @staticmethod
    def _key_for(activity: WorkActivity) -> tuple[str, str, str, str]:
        return (
            activity.plugin_id,
            activity.project_id,
            activity.source_type,
            activity.source_item_id,
        )

    @staticmethod
    def _row_for(activity: WorkActivity) -> tuple[object, ...]:
        return (
            activity.activity_id,
            activity.plugin_id,
            activity.source_system,
            activity.source_type,
            activity.source_item_id,
            activity.project_id,
            activity.workspace_name,
            activity.event_type,
            activity.title,
            activity.summary,
            activity.body_text,
            activity.status,
            activity.priority,
            activity.owner,
            activity.source_url,
            json.dumps(list(activity.tags), ensure_ascii=True),
            activity.occurred_at.isoformat(),
            activity.synced_at.isoformat(),
            activity.content_hash,
            json.dumps(activity.raw_metadata, sort_keys=True, ensure_ascii=True),
            activity.embedding_text,
        )

    @staticmethod
    def _activity_from_row(row: aiosqlite.Row) -> WorkActivity:
        return WorkActivity(
            activity_id=str(row["activity_id"]),
            plugin_id=str(row["plugin_id"]),
            source_system=str(row["source_system"]),
            source_type=str(row["source_type"]),
            source_item_id=str(row["source_item_id"]),
            project_id=str(row["project_id"]),
            workspace_name=row["workspace_name"],
            event_type=str(row["event_type"]),
            title=str(row["title"]),
            summary=str(row["summary"] or ""),
            body_text=str(row["body_text"] or ""),
            status=row["status"],
            priority=row["priority"],
            owner=row["owner"],
            source_url=row["source_url"],
            tags=tuple(json.loads(row["tags_json"] or "[]")),
            occurred_at=parse_utc_datetime(row["occurred_at"], "occurred_at"),
            synced_at=parse_utc_datetime(row["synced_at"], "synced_at"),
            content_hash=str(row["content_hash"]),
            raw_metadata=json.loads(row["raw_metadata_json"] or "{}"),
            embedding_text=str(row["embedding_text"] or ""),
        )