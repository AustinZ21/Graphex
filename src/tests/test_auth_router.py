from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from backend.auth import router as auth_router


async def _make_db(tmp_path: Path) -> aiosqlite.Connection:
    db = await aiosqlite.connect(tmp_path / "auth-router-test.db")
    db.row_factory = aiosqlite.Row
    await db.execute(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            project_key TEXT NOT NULL,
            project_id TEXT NOT NULL,
            upstream_url TEXT DEFAULT '',
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    await db.commit()
    return db


def test_candidate_repo_paths_prefers_case_insensitive_local_repo_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_router, "_LOCAL_REPOS_ROOT", tmp_path)
    (tmp_path / "OSAgent").mkdir()

    candidates = auth_router._candidate_repo_paths("osagent")

    assert candidates[0] == str(tmp_path / "OSAgent")


@pytest.mark.asyncio
async def test_trigger_project_index_calls_mcp_server_with_resolved_repo_path(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)
    await db.execute(
        "INSERT INTO projects(id, project_key, project_id, is_active) VALUES (1, 'osagent', 'OESIJQWHXY', 1)"
    )
    await db.commit()

    try:
        with patch.object(auth_router, "_resolve_repo_path", return_value="D:/Repos/OSAgent"), patch.object(
            auth_router.mcp_server,
            "index_repo_changes",
            AsyncMock(return_value={
                "status": "queued",
                "mode": "incremental",
                "job_id": "job-123",
                "stream_id": "500-0",
                "changed_count": 3,
                "destructive_count": 1,
            }),
        ) as index_repo_changes:
            result = await auth_router.trigger_project_index(1, _={"role": "admin"}, db=db)

        assert result.project_key == "osagent"
        assert result.repo_path == "D:/Repos/OSAgent"
        assert result.job_id == "job-123"
        index_repo_changes.assert_awaited_once_with(repo_path="D:/Repos/OSAgent")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_trigger_project_index_errors_when_repo_path_missing(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)
    await db.execute(
        "INSERT INTO projects(id, project_key, project_id, is_active) VALUES (1, 'missing', 'MISS123456', 1)"
    )
    await db.commit()

    try:
        with patch.object(auth_router, "_resolve_repo_path", return_value=None):
            with pytest.raises(Exception) as exc_info:
                await auth_router.trigger_project_index(1, _={"role": "admin"}, db=db)
        assert "Repository path not found" in str(exc_info.value)
    finally:
        await db.close()
