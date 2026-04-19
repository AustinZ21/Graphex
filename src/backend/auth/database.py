"""SQLite database setup and connection management for auth."""
from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite

DB_PATH = os.getenv("AUTH_DB_PATH", "/app/data/auth.db")

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'viewer',
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
        # email column
        try:
            await db.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
            await db.commit()
        except Exception:
            pass  # column already exists


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yield a connected aiosqlite connection with Row factory."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
