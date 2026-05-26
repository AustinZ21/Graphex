from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

import backend.auth.middleware as auth_middleware
import backend.main as main_module
from backend.auth import database as auth_database
from backend.auth.security import hash_token
from backend.main import app
from backend.workbriefing.service import WorkBriefingService
from backend.workbriefing.store import SqliteActivityStore


def _seed_project_auth_db(db_path: Path) -> None:
    asyncio.run(auth_database.init_db(str(db_path)))
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO projects(id, project_name, project_id, upstream_url, description, repo_path, is_active)
        VALUES(1, 'contextgraphadmin', 'CGA123', 'http://localhost:18001', 'CGA host project', 'D:/Repos/ContextGraphAdmin', 1)
        """
    )
    cur.execute(
        """
        INSERT INTO project_tokens(project_id, token_type, token_hash, token_hint, version, is_active)
        VALUES(1, 'edge_agent', ?, 'edge-tok', 1, 1)
        """,
        (hash_token("edge-token"),),
    )
    cur.execute(
        """
        INSERT INTO project_tokens(project_id, token_type, token_hash, token_hint, version, is_active)
        VALUES(1, 'mcp', ?, 'mcp-tokn', 1, 1)
        """,
        (hash_token("mcp-token"),),
    )
    con.commit()
    con.close()


def _build_client(db_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(auth_database, "DB_PATH", str(db_path))
    monkeypatch.setattr(auth_middleware, "DB_PATH", str(db_path))
    service = WorkBriefingService(store=SqliteActivityStore(db_path=str(db_path)))
    monkeypatch.setattr(main_module, "_work_briefing_service", service)
    return TestClient(app)


def test_project_api_records_activity_with_edge_agent_token(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "project-work-briefing.db"
    _seed_project_auth_db(db_path)
    client = _build_client(db_path, monkeypatch)

    response = client.post(
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
    assert payload["activity"]["workspace_name"] == "contextgraphadmin"
    assert payload["activity"]["status"] == "done"


def test_project_api_rejects_body_project_spoof(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "project-work-briefing.db"
    _seed_project_auth_db(db_path)
    client = _build_client(db_path, monkeypatch)

    response = client.post(
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


def test_project_api_summary_uses_authenticated_project_scope(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "project-work-briefing.db"
    _seed_project_auth_db(db_path)
    client = _build_client(db_path, monkeypatch)

    create_response = client.post(
        "/api/project/work-briefing/activity",
        headers={"Authorization": "Bearer edge-token"},
        json={
            "event_type": "review",
            "title": "Reviewed integration slice",
            "summary": "validated project-scoped ingestion",
        },
    )
    assert create_response.status_code == 201

    response = client.get(
        "/api/project/work-briefing?limit=10",
        headers={"Authorization": "Bearer mcp-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == "CGA123"
    assert payload["total_events"] == 1
    assert payload["project_counts"] == {"CGA123": 1}