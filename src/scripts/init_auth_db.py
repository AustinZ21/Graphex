#!/usr/bin/env python3
"""
init_auth_db.py
---------------
Bootstrap the auth SQLite database:
  1. Create tables (idempotent).
  2. Create the initial admin user (ADMIN_USERNAME / ADMIN_PASSWORD env vars,
     defaults: admin / changeme).
  3. Import projects + tokens from config/project-token-registry.json
     (skips entries that already exist).

Run once before starting the server, or on every startup (it is safe to
re-run; all inserts use INSERT OR IGNORE).

Usage:
    python -m src.scripts.init_auth_db
    # or inside Docker:
    python /app/src/scripts/init_auth_db.py
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import string
import sys
from pathlib import Path

# Allow running as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import aiosqlite

from backend.auth.database import DB_PATH, init_db
from backend.auth.security import hash_password, hash_token, token_hint

REGISTRY_PATH = os.getenv(
    "TOKEN_REGISTRY_PATH",
    str(Path(__file__).resolve().parents[2] / "config" / "project-token-registry.json"),
)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")


async def main() -> None:
    print(f"[init_auth_db] DB path: {DB_PATH}")
    await init_db()
    print("[init_auth_db] Tables ensured.")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # ── Create admin user ──────────────────────────────────────────────
        async with db.execute(
            "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
        ) as cur:
            existing = await cur.fetchone()

        if not existing:
            hashed = hash_password(ADMIN_PASSWORD)
            await db.execute(
                "INSERT INTO users(username, password_hash, role) VALUES(?,?,?)",
                (ADMIN_USERNAME, hashed, "admin"),
            )
            print(f"[init_auth_db] Admin user '{ADMIN_USERNAME}' created.")
        else:
            print(f"[init_auth_db] Admin user '{ADMIN_USERNAME}' already exists, skipping.")

        # ── Import registry ────────────────────────────────────────────────
        registry_file = Path(REGISTRY_PATH)
        if not registry_file.exists():
            print(f"[init_auth_db] Registry not found at {REGISTRY_PATH}, skipping import.")
            await db.commit()
            return

        registry = json.loads(registry_file.read_text(encoding="utf-8"))
        projects = registry.get("projects", [])
        print(f"[init_auth_db] Importing {len(projects)} project(s) from registry.")

        for proj in projects:
            project_key = proj["projectKey"]
            project_id = proj["projectId"]
            upstream_url = proj.get("upstreamUrl", "")
            description = proj.get("description", "")

            # Upsert project (INSERT OR IGNORE keeps existing rows)
            await db.execute(
                """INSERT OR IGNORE INTO projects(project_key, project_id, upstream_url, description)
                   VALUES(?,?,?,?)""",
                (project_key, project_id, upstream_url, description),
            )

            # Fetch row id
            async with db.execute(
                "SELECT id FROM projects WHERE project_key = ?", (project_key,)
            ) as cur:
                row = await cur.fetchone()
            db_project_id = row["id"]

            # Import mcp token
            mcp_raw = proj.get("mcp", {}).get("token", "")
            if mcp_raw:
                await db.execute(
                    """INSERT OR IGNORE INTO project_tokens(project_id, token_type, token_hash, token_hint)
                       VALUES(?,?,?,?)""",
                    (db_project_id, "mcp", hash_token(mcp_raw), token_hint(mcp_raw)),
                )
                print(f"[init_auth_db]   {project_key}: mcp token imported.")

            # Import edge_agent token
            edge_raw = proj.get("edgeAgent", {}).get("token", "")
            if edge_raw:
                await db.execute(
                    """INSERT OR IGNORE INTO project_tokens(project_id, token_type, token_hash, token_hint)
                       VALUES(?,?,?,?)""",
                    (db_project_id, "edge_agent", hash_token(edge_raw), token_hint(edge_raw)),
                )
                print(f"[init_auth_db]   {project_key}: edge_agent token imported.")

        await db.commit()
        print("[init_auth_db] Done.")


if __name__ == "__main__":
    asyncio.run(main())
