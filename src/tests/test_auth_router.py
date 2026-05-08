from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
            project_name TEXT NOT NULL,
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


async def _create_project_tokens_table(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE project_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            token_type TEXT NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            token_hint TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    await db.commit()


def test_candidate_repo_paths_prefers_case_insensitive_local_repo_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_router, "_LOCAL_REPOS_ROOT", tmp_path)
    (tmp_path / "OSAgent").mkdir()

    candidates = auth_router._candidate_repo_paths("osagent")

    assert candidates[0] == str(tmp_path / "OSAgent")


def test_build_index_job_status_marks_stale_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_router, "INDEX_STALE_AFTER_SEC", 60)
    old_update = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()

    status = auth_router._build_index_job_status(
        {
            "job_id": "job-stale",
            "job_type": "index_full",
            "repo_path": "D:/Repos/OSAgent",
            "status": "processing",
            "created_at": old_update,
            "updated_at": old_update,
        },
        pending_by_id={},
        avg_duration_sec=30,
        processing_remaining=0,
    )

    assert status.status == "stale"
    assert status.is_stale is True
    assert status.age_seconds is not None
    assert status.age_seconds >= 60


@pytest.mark.asyncio
async def test_generate_project_token_uses_type_prefixes(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)
    await _create_project_tokens_table(db)
    await db.execute(
        "INSERT INTO projects(id, project_name, project_id, is_active) VALUES (1, 'osagent', 'OESIJQWHXY', 1)"
    )
    await db.commit()

    try:
        mcp = await auth_router.generate_project_token(
            1,
            auth_router.GenerateTokenRequest(token_type="mcp"),
            _={"role": "admin"},
            db=db,
        )
        edge = await auth_router.generate_project_token(
            1,
            auth_router.GenerateTokenRequest(token_type="edge_agent"),
            _={"role": "admin"},
            db=db,
        )

        assert mcp.token is not None
        assert mcp.token.startswith("mcp_")
        assert mcp.token_type == "mcp"
        assert mcp.token_hint.startswith("mcp_")
        assert edge.token is not None
        assert edge.token.startswith("edge")
        assert edge.token_type == "edge_agent"
        assert edge.token_hint.startswith("edge")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_rotate_token_preserves_type_and_prefixes_new_token(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)
    await _create_project_tokens_table(db)
    await db.execute(
        "INSERT INTO projects(id, project_name, project_id, is_active) VALUES (1, 'osagent', 'OESIJQWHXY', 1)"
    )
    await db.execute(
        """
        INSERT INTO project_tokens(id, project_id, token_type, token_hash, token_hint, version, is_active)
        VALUES (13, 1, 'edge_agent', 'old-hash', 'oldedge...', 4, 1)
        """
    )
    await db.commit()

    try:
        rotated = await auth_router.rotate_token(13, _={"role": "admin"}, db=db)

        assert rotated.token_type == "edge_agent"
        assert rotated.version == 5
        assert rotated.token is not None
        assert rotated.token.startswith("edge")
        assert rotated.token_hint.startswith("edge")

        async with db.execute("SELECT is_active FROM project_tokens WHERE id = 13") as cur:
            old = await cur.fetchone()
        assert old["is_active"] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_trigger_project_index_calls_mcp_server_with_resolved_repo_path(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)
    await db.execute(
        "INSERT INTO projects(id, project_name, project_id, is_active) VALUES (1, 'osagent', 'OESIJQWHXY', 1)"
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

        assert result.project_name == "osagent"
        assert result.repo_path == "D:/Repos/OSAgent"
        assert result.job_id == "job-123"
        index_repo_changes.assert_awaited_once_with(repo_path="D:/Repos/OSAgent", project_name="osagent")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_trigger_project_index_errors_when_repo_path_missing(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)
    await db.execute(
        "INSERT INTO projects(id, project_name, project_id, is_active) VALUES (1, 'missing', 'MISS123456', 1)"
    )
    await db.commit()

    try:
        with patch.object(auth_router, "_resolve_repo_path", return_value=None):
            with pytest.raises(Exception) as exc_info:
                await auth_router.trigger_project_index(1, _={"role": "admin"}, db=db)
        assert "Repository path not found" in str(exc_info.value)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_list_projects_index_status_includes_queue_position_and_eta(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)
    await db.execute(
        "INSERT INTO projects(id, project_name, project_id, is_active) VALUES (1, 'osagent', 'OESIJQWHXY', 1)"
    )
    await db.commit()

    consumer = AsyncMock()
    consumer.get_queue_snapshot.return_value = {
        "pending_jobs": [
            {
                "job_id": "job-001",
                "status": "pending",
                "created_at": "2026-04-19T17:18:41+00:00",
            }
        ],
        "processing_jobs": [
            {
                "job_id": "job-000",
                "status": "processing",
                "updated_at": "2026-04-19T17:18:50+00:00",
            }
        ],
        "avg_duration_sec": 40,
    }
    consumer.get_jobs_by_repo.return_value = [
        {
            "job_id": "job-001",
            "job_type": "index_incremental",
            "repo_path": "D:/Repos/OSAgent",
            "status": "pending",
            "created_at": "2026-04-19T17:18:41+00:00",
            "updated_at": "2026-04-19T17:18:41+00:00",
        }
    ]

    try:
        with patch.object(auth_router, "_candidate_repo_paths", return_value=["D:/Repos/OSAgent"]):
            result = await auth_router.list_projects_index_status(
                _={"username": "admin", "role": "admin"},
                db=db,
                consumer=consumer,
            )

        assert len(result) == 1
        assert result[0].latest_job is not None
        assert result[0].latest_job.queue_position == 1
        assert result[0].latest_job.eta_seconds is not None
        assert result[0].latest_job.eta_seconds >= 40
        assert len(result[0].recent_jobs) == 1
        assert result[0].recent_jobs[0].job_id == "job-001"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_list_projects_index_status_uses_latest_job_across_repo_path_variants(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)
    await db.execute(
        "INSERT INTO projects(id, project_name, project_id, is_active) VALUES (1, 'browseragent', '20YYYTOHV8', 1)"
    )
    await db.commit()

    consumer = AsyncMock()
    consumer.get_queue_snapshot.return_value = {
        "pending_jobs": [],
        "processing_jobs": [],
        "avg_duration_sec": 30,
    }
    consumer.get_jobs_by_repo.side_effect = [
        [
            {
                "job_id": "old-job",
                "job_type": "index_full",
                "repo_path": "D:/Repos/BrowserAgent",
                "status": "done",
                "created_at": "2026-04-19T05:04:43+00:00",
                "updated_at": "2026-04-19T05:05:28+00:00",
            }
        ],
        [
            {
                "job_id": "new-job",
                "job_type": "index_incremental",
                "repo_path": "/repos/browseragent",
                "status": "pending",
                "created_at": "2026-04-19T18:05:28+00:00",
                "updated_at": "2026-04-19T18:05:28+00:00",
            }
        ],
    ]

    try:
        with patch.object(auth_router, "_candidate_repo_paths", return_value=["D:/Repos/BrowserAgent", "/repos/browseragent"]):
            result = await auth_router.list_projects_index_status(
                _={"username": "admin", "role": "admin"},
                db=db,
                consumer=consumer,
            )

        assert len(result) == 1
        assert result[0].latest_job is not None
        assert result[0].latest_job.job_id == "new-job"
        assert result[0].latest_job.status == "pending"
        assert len(result[0].recent_jobs) == 2
        assert [job.job_id for job in result[0].recent_jobs] == ["new-job", "old-job"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_recover_project_stale_index_jobs_delegates_to_consumer(tmp_path: Path) -> None:
    db = await _make_db(tmp_path)
    await db.execute(
        "INSERT INTO projects(id, project_name, project_id, is_active) VALUES (1, 'osagent', 'OESIJQWHXY', 1)"
    )
    await db.commit()

    recovered_at = datetime.now(timezone.utc).isoformat()
    consumer = AsyncMock()
    consumer.recover_stale_jobs_by_repo.return_value = [
        {
            "job_id": "job-stale",
            "job_type": "index_full",
            "repo_path": "D:/Repos/OSAgent",
            "status": "failed",
            "created_at": recovered_at,
            "updated_at": recovered_at,
            "error": "Recovered stale processing job after 120s without status updates",
        }
    ]

    try:
        with patch.object(auth_router, "_resolve_repo_path", return_value="D:/Repos/OSAgent"), patch.object(
            auth_router,
            "_candidate_repo_paths",
            return_value=["D:/Repos/OSAgent"],
        ):
            result = await auth_router.recover_project_stale_index_jobs(
                1,
                _={"role": "admin"},
                db=db,
                consumer=consumer,
            )

        assert result.recovered_count == 1
        assert result.recovered_jobs[0].status == "failed"
        consumer.recover_stale_jobs_by_repo.assert_awaited_once_with(
            ["D:/Repos/OSAgent"],
            auth_router.INDEX_STALE_AFTER_SEC,
        )
    finally:
        await db.close()
