#!/usr/bin/env python3
"""One-shot migration of the legacy auth.db SQLite database into PostgreSQL.

Reads ``users``, ``projects``, ``project_tokens``, and ``audit_logs`` from
a SQLite file produced by the pre-pgshim CGA build and inserts them into
the new Postgres schema defined in :mod:`backend.auth.database`.

The migration is idempotent: each row is upserted by its natural key
(``username``, ``project_name``, ``token_hash``, ``id``); existing rows
are left untouched.  After the copy, each table's ``BIGSERIAL`` sequence
is fast-forwarded to ``max(id) + 1`` so future inserts don't collide.

Usage
-----
::

    python -m src.scripts.migrate_auth_to_pg --sqlite /path/to/auth.db
    # explicit DSN override:
    python -m src.scripts.migrate_auth_to_pg --sqlite ./auth.db \
        --dsn postgresql://app:app@localhost:15432/appdb
    # dry-run prints counts but skips inserts:
    python -m src.scripts.migrate_auth_to_pg --sqlite ./auth.db --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.auth.database import init_db
from backend.auth.pgshim import get_pool, resolve_auth_dsn

TABLES = ("users", "projects", "project_tokens", "audit_logs")


def _sqlite_rows(db_path: Path, table: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(f"SELECT * FROM {table}")
        return cur.fetchall()
    finally:
        conn.close()


def _columns(rows: list[sqlite3.Row]) -> list[str]:
    return list(rows[0].keys()) if rows else []


async def _copy_table(pool, table: str, rows: list[sqlite3.Row], dry: bool) -> int:
    if not rows:
        print(f"[migrate_auth] {table}: 0 rows in source, skipping")
        return 0

    cols = _columns(rows)
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    conflict_target = {
        "users": "username",
        "projects": "project_name",
        "project_tokens": "token_hash",
        "audit_logs": "id",
    }[table]

    sql = (
        f"INSERT INTO {table}({col_list}) VALUES({placeholders}) "
        f"ON CONFLICT ({conflict_target}) DO NOTHING"
    )
    if dry:
        print(f"[migrate_auth] {table}: would copy {len(rows)} rows (dry-run)")
        return 0

    # Use the underlying asyncpg connection for executemany; this is
    # ~50-100x faster than individual round-trips for large tables
    # (audit_logs has hundreds of thousands of rows).
    from backend.auth.pgshim import translate_placeholders

    pg_sql = translate_placeholders(sql)
    batch_size = 2000
    inserted = 0
    async with pool.acquire() as db:
        conn = db.raw  # raw asyncpg.Connection

        # Build per-column coercers based on PG type info.  SQLite is
        # dynamically typed and happily stored, e.g., numeric GitHub IDs
        # in TEXT columns; asyncpg rejects type mismatches.
        type_rows = await conn.fetch(
            """
            SELECT a.attname, format_type(a.atttypid, a.atttypmod) AS pgtype
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            WHERE c.relname = $1 AND a.attnum > 0 AND NOT a.attisdropped
            """,
            table,
        )
        pgtypes = {r["attname"]: r["pgtype"] for r in type_rows}

        def _coerce(col: str, val):
            if val is None:
                return None
            pgtype = pgtypes.get(col, "")
            # Force int/float -> str when target column is text-like.
            if pgtype in {"text", "character varying"} and not isinstance(val, str):
                return str(val)
            # SQLite stores BLOBs as bytes; everything else passes through.
            return val

        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            args = [tuple(_coerce(c, row[c]) for c in cols) for row in chunk]
            await conn.executemany(pg_sql, args)
            inserted += len(chunk)
            if len(rows) > batch_size:
                print(
                    f"[migrate_auth] {table}: {inserted}/{len(rows)} rows...",
                    flush=True,
                )
    print(f"[migrate_auth] {table}: copied {inserted}/{len(rows)} rows")
    return inserted


async def _resync_sequence(pool, table: str) -> None:
    """Fast-forward the BIGSERIAL ``id`` sequence past the imported max(id)."""
    async with pool.acquire() as db:
        async with db.execute(
            f"SELECT setval(pg_get_serial_sequence(?, 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1), true)",
            (table,),
        ) as cur:
            row = await cur.fetchone()
            new_val = row[0] if row else None
    print(f"[migrate_auth] {table}: sequence -> {new_val}")


async def main_async(args: argparse.Namespace) -> int:
    sqlite_path = Path(args.sqlite)
    if not sqlite_path.is_file():
        print(f"[migrate_auth] sqlite file not found: {sqlite_path}", file=sys.stderr)
        return 2

    dsn = resolve_auth_dsn(args.dsn)
    print(f"[migrate_auth] source SQLite : {sqlite_path}")
    print(f"[migrate_auth] target PG DSN : {dsn}")
    print(f"[migrate_auth] dry run       : {args.dry_run}")

    # Ensure target schema exists.
    await init_db(dsn)
    pool = get_pool()

    total = 0
    for table in TABLES:
        try:
            rows = _sqlite_rows(sqlite_path, table)
        except sqlite3.OperationalError as exc:
            print(f"[migrate_auth] {table}: source table missing ({exc}), skipping")
            continue
        total += await _copy_table(pool, table, rows, args.dry_run)

    if not args.dry_run:
        for table in TABLES:
            try:
                await _resync_sequence(pool, table)
            except Exception as exc:  # pragma: no cover - best effort
                print(f"[migrate_auth] {table}: sequence resync failed: {exc}")

    print(f"[migrate_auth] done. total rows inserted = {total}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", required=True, help="path to legacy auth.db")
    parser.add_argument("--dsn", help="target Postgres DSN (defaults to CGA_POSTGRES_DSN env)")
    parser.add_argument("--dry-run", action="store_true", help="report counts without inserting")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
