"""SQLite database setup and connection management for auth."""
from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncGenerator
import json
from datetime import datetime, timezone

import aiosqlite

DB_PATH = os.getenv("AUTH_DB_PATH", "/app/data/auth.db")

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    auth_provider TEXT    NOT NULL DEFAULT 'local',
    github_id     TEXT    UNIQUE,
    role          TEXT    NOT NULL DEFAULT 'developer',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    project_key  TEXT    UNIQUE NOT NULL,
    project_id   TEXT    UNIQUE NOT NULL,
    upstream_url TEXT    NOT NULL DEFAULT '',
    description  TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS project_tokens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    token_type  TEXT    NOT NULL,
    token_hash  TEXT    UNIQUE NOT NULL,
    token_hint  TEXT    NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_token_hash
    ON project_tokens(token_hash)
    WHERE is_active = 1;

CREATE TABLE IF NOT EXISTS audit_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    scope           TEXT    NOT NULL,
    method          TEXT    NOT NULL,
    path            TEXT    NOT NULL,
    status_code     INTEGER NOT NULL,
    duration_ms     INTEGER NOT NULL,
    actor_type      TEXT    NOT NULL DEFAULT 'anonymous',
    actor_id        INTEGER,
    actor_name      TEXT,
    project_id      INTEGER,
    project_key     TEXT,
    token_id        INTEGER,
    client_ip       TEXT,
    user_agent      TEXT,
    query_string    TEXT,
    request_body    TEXT,
    response_error  TEXT,
    details_json    TEXT,
    token_usage_total INTEGER
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_scope ON audit_logs(scope);
CREATE INDEX IF NOT EXISTS idx_audit_logs_project_id ON audit_logs(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_name ON audit_logs(actor_name);
"""


async def init_db() -> None:
    """Create tables if they do not exist."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_CREATE_TABLES)
        # Migrations: add columns that may not exist in older DBs
        try:
            await db.execute("ALTER TABLE project_tokens ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            await db.commit()
        except Exception:
            pass  # column already exists
        # audit token usage column
        try:
            await db.execute("ALTER TABLE audit_logs ADD COLUMN token_usage_total INTEGER")
            await db.commit()
        except Exception:
            pass  # column already exists
        # email column
        try:
            await db.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
            await db.commit()
        except Exception:
            pass  # column already exists
        # oauth provider columns
        try:
            await db.execute("ALTER TABLE users ADD COLUMN auth_provider TEXT NOT NULL DEFAULT 'local'")
            await db.commit()
        except Exception:
            pass  # column already exists
        try:
            await db.execute("ALTER TABLE users ADD COLUMN github_id TEXT")
            await db.commit()
        except Exception:
            pass  # column already exists
        try:
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id) WHERE github_id IS NOT NULL")
            await db.commit()
        except Exception:
            pass  # index creation best-effort
        # role rename: viewer -> developer
        try:
            await db.execute("UPDATE users SET role = 'developer' WHERE role = 'viewer'")
            await db.commit()
        except Exception:
            pass  # best-effort migration


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yield a connected aiosqlite connection with Row factory."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


def _truncate_text(value: str | None, max_len: int = 2000) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= max_len else (text[: max_len - 1] + "…")


async def insert_audit_log(
    *,
    scope: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    actor_type: str = "anonymous",
    actor_id: int | None = None,
    actor_name: str | None = None,
    project_id: int | None = None,
    project_key: str | None = None,
    token_id: int | None = None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    query_string: str | None = None,
    request_body: str | None = None,
    response_error: str | None = None,
    details: dict | None = None,
    token_usage_total: int | None = None,
) -> None:
    """Write a normalized audit row for admin troubleshooting and compliance."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()
    details_json = json.dumps(details, ensure_ascii=True) if details else None
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO audit_logs(
                created_at, scope, method, path, status_code, duration_ms,
                actor_type, actor_id, actor_name,
                project_id, project_key, token_id,
                client_ip, user_agent, query_string, request_body, response_error, details_json, token_usage_total
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                created_at,
                scope,
                method,
                path,
                status_code,
                max(0, int(duration_ms)),
                actor_type,
                actor_id,
                _truncate_text(actor_name, 128),
                project_id,
                _truncate_text(project_key, 128),
                token_id,
                _truncate_text(client_ip, 128),
                _truncate_text(user_agent, 512),
                _truncate_text(query_string, 512),
                _truncate_text(request_body, 2000),
                _truncate_text(response_error, 1000),
                _truncate_text(details_json, 4000),
                int(token_usage_total) if token_usage_total is not None else None,
            ),
        )
        await db.commit()
