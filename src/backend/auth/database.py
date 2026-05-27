"""PostgreSQL-backed auth database (asyncpg via the aiosqlite-shim).

History
-------
This module previously used aiosqlite against ``/app/data/auth.db``.
It has been migrated to PostgreSQL.  The schema deliberately mirrors
the original SQLite layout — ``BIGSERIAL`` for autoincrement ids,
``INTEGER`` for boolean flags, ``TEXT`` for ISO-8601 timestamps — so
that the SQL emitted by :mod:`backend.auth.router` and friends
continues to work unchanged.

Public surface
--------------
* :data:`DB_PATH` — kept for backward compatibility but now holds the
  active PostgreSQL DSN string (logged at startup, used by tests).
* :func:`init_db` — create tables if missing.
* :func:`get_db` — FastAPI dependency yielding a shimmed connection.
* :func:`insert_audit_log` — write a single audit row.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncGenerator

from backend.auth.pgshim import (
    Connection,
    get_pool,
    init_pool,
    resolve_auth_dsn,
)

# ``DB_PATH`` historically held a filesystem path; we keep the name so
# existing imports (middleware, main, scripts) continue to work but it
# now stores the active Postgres DSN.  Callers that only need a label
# can use this verbatim; callers that mutate or open files based on it
# have been updated.
DB_PATH = resolve_auth_dsn()


_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    email         TEXT    NOT NULL DEFAULT '',
    auth_provider TEXT    NOT NULL DEFAULT 'local',
    github_id     TEXT    UNIQUE,
    role          TEXT    NOT NULL DEFAULT 'developer',
    created_at    TEXT    NOT NULL DEFAULT to_char((now() at time zone 'utc'), 'YYYY-MM-DD"T"HH24:MI:SS'),
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id
    ON users(github_id)
    WHERE github_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS projects (
    id           BIGSERIAL PRIMARY KEY,
    project_name TEXT    UNIQUE NOT NULL,
    project_id   TEXT    UNIQUE NOT NULL,
    upstream_url TEXT    NOT NULL DEFAULT '',
    description  TEXT    NOT NULL DEFAULT '',
    repo_path    TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT to_char((now() at time zone 'utc'), 'YYYY-MM-DD"T"HH24:MI:SS'),
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS project_tokens (
    id          BIGSERIAL PRIMARY KEY,
    project_id  BIGINT  NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    token_type  TEXT    NOT NULL,
    token_hash  TEXT    UNIQUE NOT NULL,
    token_hint  TEXT    NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT to_char((now() at time zone 'utc'), 'YYYY-MM-DD"T"HH24:MI:SS'),
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_token_hash
    ON project_tokens(token_hash)
    WHERE is_active = 1;

CREATE TABLE IF NOT EXISTS audit_logs (
    id                BIGSERIAL PRIMARY KEY,
    created_at        TEXT    NOT NULL DEFAULT to_char((now() at time zone 'utc'), 'YYYY-MM-DD"T"HH24:MI:SS'),
    scope             TEXT    NOT NULL,
    method            TEXT    NOT NULL,
    path              TEXT    NOT NULL,
    status_code       INTEGER NOT NULL,
    duration_ms       INTEGER NOT NULL,
    actor_type        TEXT    NOT NULL DEFAULT 'anonymous',
    actor_id          BIGINT,
    actor_name        TEXT,
    project_id        BIGINT,
    project_name      TEXT,
    token_id          BIGINT,
    client_ip         TEXT,
    user_agent        TEXT,
    query_string      TEXT,
    request_body      TEXT,
    response_error    TEXT,
    details_json      TEXT,
    token_usage_total BIGINT
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_scope       ON audit_logs(scope);
CREATE INDEX IF NOT EXISTS idx_audit_logs_project_id  ON audit_logs(project_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_name  ON audit_logs(actor_name);
"""


async def init_db(dsn: str | None = None) -> None:
    """Ensure tables exist.  Idempotent and safe to call on every startup."""
    pool = await init_pool(dsn)
    async with pool.acquire() as db:
        await db.executescript(_CREATE_TABLES)
        # Best-effort legacy role rename.
        try:
            await db.execute("UPDATE users SET role = 'developer' WHERE role = 'viewer'")
        except Exception:
            pass


async def get_db() -> AsyncGenerator[Connection, None]:
    """FastAPI dependency yielding a shimmed connection from the pool."""
    pool = get_pool()
    async with pool.acquire() as db:
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
    project_name: str | None = None,
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
    created_at = datetime.now(timezone.utc).isoformat()
    details_json = json.dumps(details, ensure_ascii=True) if details else None
    pool = get_pool()
    async with pool.acquire() as db:
        await db.execute(
            """
            INSERT INTO audit_logs(
                created_at, scope, method, path, status_code, duration_ms,
                actor_type, actor_id, actor_name,
                project_id, project_name, token_id,
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
                _truncate_text(project_name, 128),
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
