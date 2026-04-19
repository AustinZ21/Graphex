import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.auth.middleware as auth_mw
from backend.auth.middleware import ProjectTokenMiddleware
from backend.auth.security import hash_token


def _setup_db(path: str) -> None:
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_key TEXT UNIQUE NOT NULL,
            project_id TEXT UNIQUE NOT NULL,
            upstream_url TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE project_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            token_type TEXT NOT NULL,
            token_hash TEXT UNIQUE NOT NULL,
            token_hint TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            is_active INTEGER NOT NULL DEFAULT 1
        );
        """
    )

    cur.execute(
        "INSERT INTO projects(id, project_key, project_id, is_active) VALUES(1, 'p1', 'P1', 1)"
    )
    cur.execute(
        "INSERT INTO projects(id, project_key, project_id, is_active) VALUES(2, 'p2', 'P2', 1)"
    )
    cur.execute(
        "INSERT INTO project_tokens(project_id, token_type, token_hash, token_hint, is_active) VALUES(1, 'mcp', ?, 'goodtok...', 1)",
        (hash_token('good-token'),),
    )
    cur.execute(
        "INSERT INTO project_tokens(project_id, token_type, token_hash, token_hint, is_active) VALUES(1, 'edge_agent', ?, 'edgetok...', 1)",
        (hash_token('edge-token'),),
    )
    con.commit()
    con.close()


def _build_client(db_path: str, monkeypatch) -> TestClient:
    monkeypatch.setattr(auth_mw, "DB_PATH", db_path)

    app = FastAPI()
    app.add_middleware(ProjectTokenMiddleware)

    @app.get("/mcp/ping")
    async def ping() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_mcp_rejects_missing_project_id(tmp_path, monkeypatch):
    db = tmp_path / "auth.db"
    _setup_db(str(db))
    client = _build_client(str(db), monkeypatch)

    resp = client.get("/mcp/ping", headers={"Authorization": "Bearer good-token"})

    assert resp.status_code == 401
    assert "Missing project_id" in resp.json()["detail"]


def test_mcp_rejects_non_mcp_token_type(tmp_path, monkeypatch):
    db = tmp_path / "auth.db"
    _setup_db(str(db))
    client = _build_client(str(db), monkeypatch)

    resp = client.get(
        "/mcp/ping",
        headers={
            "Authorization": "Bearer edge-token",
            "X-Project-ID": "P1",
        },
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Token type not allowed for MCP endpoint"


def test_mcp_rejects_project_mismatch(tmp_path, monkeypatch):
    db = tmp_path / "auth.db"
    _setup_db(str(db))
    client = _build_client(str(db), monkeypatch)

    resp = client.get(
        "/mcp/ping",
        headers={
            "Authorization": "Bearer good-token",
            "X-Project-ID": "P2",
        },
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Token is not valid for this project_id"


def test_mcp_accepts_matching_mcp_token(tmp_path, monkeypatch):
    db = tmp_path / "auth.db"
    _setup_db(str(db))
    client = _build_client(str(db), monkeypatch)

    resp = client.get(
        "/mcp/ping",
        headers={
            "Authorization": "Bearer good-token",
            "X-Project-ID": "P1",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
