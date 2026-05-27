from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.workbriefing.models import WorkActivity, parse_utc_datetime
from backend.workbriefing.store import ActivityStore, ActivityUpsertResult, PgVectorActivityStore


PLUGIN_ID = "workassist.mcp.activity"
SOURCE_SYSTEM = "workassist_mcp"
SOURCE_TYPE = "work_activity"


class WorkActivityValidationError(ValueError):
    pass


class WorkBriefingService:
    def __init__(self, store: ActivityStore | None = None) -> None:
        self._store: ActivityStore = store or PgVectorActivityStore()

    async def record_activity(self, payload: dict[str, Any]) -> ActivityUpsertResult:
        project_id = self._required_string(payload, "project_id")
        event_type = self._required_string(payload, "event_type")
        title = self._required_string(payload, "title")
        occurred_at = parse_utc_datetime(payload.get("occurred_at"), "occurred_at")
        synced_at = datetime.now(timezone.utc)

        summary = self._optional_string(payload, "summary") or ""
        body_text = self._optional_string(payload, "body_text") or ""
        workspace_name = self._optional_string(payload, "workspace_name")
        status = self._optional_string(payload, "status")
        priority = self._optional_string(payload, "priority")
        owner = self._optional_string(payload, "owner")
        source_url = self._optional_string(payload, "source_url")
        tags = self._normalize_tags(payload.get("tags"))
        raw_metadata = self._normalize_metadata(payload.get("metadata"))

        content_hash = self._content_hash(
            {
                "project_id": project_id,
                "workspace_name": workspace_name,
                "event_type": event_type,
                "title": title,
                "summary": summary,
                "body_text": body_text,
                "status": status,
                "priority": priority,
                "owner": owner,
                "source_url": source_url,
                "tags": tags,
                "occurred_at": occurred_at.isoformat(),
                "metadata": raw_metadata,
            }
        )
        source_item_id = self._optional_string(payload, "external_id") or f"generated:{content_hash[:24]}"
        activity_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{PLUGIN_ID}:{project_id}:{source_item_id}"))
        embedding_text = self._build_embedding_text(project_id, event_type, title, summary, body_text, tags, status)

        activity = WorkActivity(
            activity_id=activity_id,
            plugin_id=PLUGIN_ID,
            source_system=SOURCE_SYSTEM,
            source_type=SOURCE_TYPE,
            source_item_id=source_item_id,
            project_id=project_id,
            workspace_name=workspace_name,
            event_type=event_type,
            title=title,
            summary=summary,
            body_text=body_text,
            status=status,
            priority=priority,
            owner=owner,
            source_url=source_url,
            tags=tags,
            occurred_at=occurred_at,
            synced_at=synced_at,
            content_hash=content_hash,
            raw_metadata=raw_metadata,
            embedding_text=embedding_text,
        )
        return await self._store.upsert(activity)

    async def list_recent(self, project_id: str | None = None, limit: int = 25) -> list[WorkActivity]:
        return await self._store.list_recent(project_id=project_id, limit=limit)

    async def get_briefing(self, project_id: str | None = None, limit: int = 25) -> dict[str, Any]:
        activities = await self.list_recent(project_id=project_id, limit=limit)
        event_type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        project_counts: dict[str, int] = {}

        for activity in activities:
            event_type_counts[activity.event_type] = event_type_counts.get(activity.event_type, 0) + 1
            project_counts[activity.project_id] = project_counts.get(activity.project_id, 0) + 1
            if activity.status:
                status_counts[activity.status] = status_counts.get(activity.status, 0) + 1

        return {
            "project_id": project_id,
            "total_events": len(activities),
            "event_type_counts": event_type_counts,
            "status_counts": status_counts,
            "project_counts": project_counts,
            "activities": [activity.to_dict() for activity in activities],
        }

    @staticmethod
    def _required_string(payload: dict[str, Any], field_name: str) -> str:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise WorkActivityValidationError(f"{field_name} is required")
        return value.strip()

    @staticmethod
    def _optional_string(payload: dict[str, Any], field_name: str) -> str | None:
        value = payload.get(field_name)
        if value is None:
            return None
        if not isinstance(value, str):
            raise WorkActivityValidationError(f"{field_name} must be a string")
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _normalize_tags(value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise WorkActivityValidationError("tags must be a list of strings")

        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise WorkActivityValidationError("tags must be a list of strings")
            cleaned = item.strip()
            if cleaned and cleaned not in seen:
                normalized.append(cleaned)
                seen.add(cleaned)
        return tuple(normalized)

    @staticmethod
    def _normalize_metadata(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise WorkActivityValidationError("metadata must be an object")
        try:
            json.dumps(value, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise WorkActivityValidationError("metadata must be JSON serializable") from exc
        return value

    @staticmethod
    def _content_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _build_embedding_text(
        project_id: str,
        event_type: str,
        title: str,
        summary: str,
        body_text: str,
        tags: tuple[str, ...],
        status: str | None,
    ) -> str:
        sections = [
            f"Project: {project_id}",
            f"Event: {event_type}",
            f"Title: {title}",
        ]
        if status:
            sections.append(f"Status: {status}")
        if summary:
            sections.append(f"Summary: {summary}")
        if body_text:
            sections.append(f"Body: {body_text}")
        if tags:
            sections.append(f"Tags: {', '.join(tags)}")
        return "\n".join(sections)