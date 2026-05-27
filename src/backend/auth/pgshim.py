"""Thin asyncpg shim that mimics the slice of aiosqlite's API used by the
auth layer (router.py, middleware.py, dependencies.py, init_auth_db.py,
main.py).

Why this exists
---------------
The CGA auth code was originally written against aiosqlite using the
``?`` placeholder dialect, ``async with db.execute(...) as cur`` cursor
context managers, and ``aiosqlite.Row``/``IntegrityError`` types.  We
have now moved the underlying store to PostgreSQL (asyncpg).  Instead
of rewriting every endpoint and SQL string, this shim presents an
aiosqlite-like surface on top of an asyncpg connection pool:

* ``?`` placeholders are translated to ``$1, $2, ...`` automatically.
* ``execute(...)`` returns an async-context-manager cursor exposing
  ``fetchone()``, ``fetchall()`` and async iteration over rows.
* ``Row`` is asyncpg's ``Record`` (already supports ``row["col"]`` and
  ``dict(row)``); we re-export the name for backwards compatibility.
* ``IntegrityError`` re-exports ``asyncpg.exceptions.IntegrityConstraintViolationError``
  so existing ``except aiosqlite.IntegrityError`` blocks keep working
  once the import is swapped.
* ``commit()`` is a no-op because asyncpg auto-commits outside of an
  explicit transaction.
* A FastAPI dependency ``get_db`` yields a shimmed connection acquired
  from the shared pool.

Schema notes
------------
The PostgreSQL schema mirrors the original SQLite schema as closely as
possible (``INTEGER`` booleans, ``TEXT`` ISO-8601 timestamps,
``BIGSERIAL`` ids) so that existing SQL works untouched.  This is a
deliberate trade-off favouring zero-risk surface migration over
idiomatic Postgres typing.
"""
from __future__ import annotations

import os
import re
from typing import Any, AsyncIterator, Iterable, Optional

import asyncpg
from asyncpg.exceptions import (
    IntegrityConstraintViolationError as IntegrityError,  # re-export
    UniqueViolationError,
    ForeignKeyViolationError,
)

__all__ = [
    "IntegrityError",
    "UniqueViolationError",
    "ForeignKeyViolationError",
    "Row",
    "Connection",
    "PgPool",
    "get_pool",
    "init_pool",
    "close_pool",
    "resolve_auth_dsn",
    "translate_placeholders",
]

# asyncpg.Record already supports row["col"] and dict(row) lookups, so
# we can reuse it as the row factory type for callers expecting
# aiosqlite.Row.
Row = asyncpg.Record


# ── DSN resolution ────────────────────────────────────────────────────────
DEFAULT_DSN_ENVS = ("CGA_POSTGRES_DSN", "WORKBRIEFING_POSTGRES_DSN")
DEFAULT_DSN = "postgresql://app:app@localhost:15432/appdb"


def resolve_auth_dsn(explicit: Optional[str] = None) -> str:
    """Pick the first non-empty DSN from explicit arg, env vars, or default."""
    if explicit:
        return explicit
    for name in DEFAULT_DSN_ENVS:
        value = os.getenv(name)
        if value:
            return value
    return DEFAULT_DSN


# ── Placeholder translation ───────────────────────────────────────────────
# Translate sqlite-style ``?`` placeholders into asyncpg's ``$1, $2, ...``.
# We have to skip ``?`` characters that appear inside string literals; the
# auth SQL is hand-written and doesn't contain any, but we still defend
# against them to keep the shim safe for future queries.
_STRING_LITERAL_RE = re.compile(r"'(?:''|[^'])*'", re.DOTALL)


def translate_placeholders(sql: str) -> str:
    """Replace ``?`` placeholders with ``$1, $2, ...`` (asyncpg style)."""
    if "?" not in sql:
        return sql

    # Mask string literals so embedded ``?`` characters aren't replaced.
    masks: list[str] = []

    def _mask(match: re.Match[str]) -> str:
        masks.append(match.group(0))
        return f"\x00LIT{len(masks) - 1}\x00"

    masked = _STRING_LITERAL_RE.sub(_mask, sql)

    counter = {"n": 0}

    def _replace(_: re.Match[str]) -> str:
        counter["n"] += 1
        return f"${counter['n']}"

    translated = re.sub(r"\?", _replace, masked)

    # Restore the literals.
    def _unmask(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        return masks[idx]

    return re.sub(r"\x00LIT(\d+)\x00", _unmask, translated)


# ── Cursor / connection wrappers ──────────────────────────────────────────
class _Cursor:
    """Async-context-manager cursor exposing fetchone/fetchall/iteration.

    Mirrors the subset of ``aiosqlite.Cursor`` used by the auth code.
    """

    def __init__(self, rows: list[asyncpg.Record]) -> None:
        self._rows = rows
        self._index = 0

    async def __aenter__(self) -> "_Cursor":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # asyncpg has no per-cursor close; we just drop the reference.
        self._rows = []

    async def fetchone(self) -> Optional[asyncpg.Record]:
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    async def fetchall(self) -> list[asyncpg.Record]:
        remaining = self._rows[self._index :]
        self._index = len(self._rows)
        return remaining

    def __aiter__(self) -> AsyncIterator[asyncpg.Record]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[asyncpg.Record]:
        while self._index < len(self._rows):
            row = self._rows[self._index]
            self._index += 1
            yield row


class _ExecuteResult:
    """Dual-mode return value mimicking ``aiosqlite.Cursor``-coroutine.

    aiosqlite's ``db.execute(sql, params)`` returns an object that is
    *both* awaitable (``await db.execute(...)``) and an async context
    manager (``async with db.execute(...) as cur``).  We replicate that
    behaviour so router code can use either form unchanged.
    """

    def __init__(self, conn: asyncpg.Connection, sql: str, params: Iterable[Any]) -> None:
        self._conn = conn
        self._sql = translate_placeholders(sql)
        self._args = tuple(params) if params else ()
        self._cursor: Optional[_Cursor] = None

    async def _run(self) -> _Cursor:
        if self._cursor is None:
            rows = await self._conn.fetch(self._sql, *self._args)
            self._cursor = _Cursor(rows)
        return self._cursor

    # Awaitable interface: ``await db.execute(...)`` resolves to the cursor.
    def __await__(self):
        return self._run().__await__()

    # Async-context-manager interface:
    # ``async with db.execute(...) as cur:`` enters by running the query.
    async def __aenter__(self) -> _Cursor:
        return await self._run()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._cursor is not None:
            await self._cursor.__aexit__(exc_type, exc, tb)


class Connection:
    """aiosqlite-compatible wrapper around an asyncpg connection.

    Created by :class:`PgPool` and yielded from :func:`get_db`.  Callers
    should not instantiate this directly.
    """

    # row_factory exists purely for compatibility with code that does
    # ``db.row_factory = aiosqlite.Row``; it's a no-op because asyncpg
    # records already behave like rows.
    row_factory: Any = Row

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    @property
    def raw(self) -> asyncpg.Connection:
        return self._conn

    def execute(self, sql: str, params: Iterable[Any] = ()) -> _ExecuteResult:
        """Run a SQL statement.  Returns a dual-mode object that can be
        awaited or used as an async context manager (see :class:`_ExecuteResult`).
        """
        return _ExecuteResult(self._conn, sql, params)

    async def executescript(self, sql_script: str) -> None:
        """Run a multi-statement DDL script (aiosqlite parity)."""
        await self._conn.execute(sql_script)

    async def commit(self) -> None:
        """No-op: asyncpg auto-commits outside explicit transactions."""
        return None


class PgPool:
    """Lazy-initialised asyncpg pool, wrapped to hand out :class:`Connection`."""

    def __init__(
        self,
        dsn: str,
        min_size: int = 1,
        max_size: int = 10,
        server_settings: Optional[dict] = None,
    ) -> None:
        self._dsn = dsn
        self._min = min_size
        self._max = max_size
        self._server_settings = server_settings
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def dsn(self) -> str:
        return self._dsn

    async def open(self) -> None:
        if self._pool is None:
            kwargs = {
                "dsn": self._dsn,
                "min_size": self._min,
                "max_size": self._max,
            }
            if self._server_settings:
                kwargs["server_settings"] = self._server_settings
            self._pool = await asyncpg.create_pool(**kwargs)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def acquire(self) -> "_AcquireCtx":
        if self._pool is None:
            raise RuntimeError("PgPool not opened; call open() during startup")
        return _AcquireCtx(self._pool)


class _AcquireCtx:
    """Async context manager that hands back a shimmed :class:`Connection`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._inner = None
        self._conn: Optional[asyncpg.Connection] = None

    async def __aenter__(self) -> Connection:
        self._inner = self._pool.acquire()
        self._conn = await self._inner.__aenter__()
        return Connection(self._conn)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._inner is not None:
            await self._inner.__aexit__(exc_type, exc, tb)
        self._inner = None
        self._conn = None


# ── Process-wide singleton ────────────────────────────────────────────────
_GLOBAL_POOL: Optional[PgPool] = None


async def init_pool(
    dsn: Optional[str] = None,
    *,
    server_settings: Optional[dict] = None,
) -> PgPool:
    """Initialise the process-wide pool. Idempotent; safe to call once at
    application startup.
    """
    global _GLOBAL_POOL
    if _GLOBAL_POOL is None:
        _GLOBAL_POOL = PgPool(resolve_auth_dsn(dsn), server_settings=server_settings)
    await _GLOBAL_POOL.open()
    return _GLOBAL_POOL


def set_pool(pool: Optional[PgPool]) -> Optional[PgPool]:
    """Replace the process-wide pool and return the previous value.

    Intended for test fixtures that swap in a per-test schema-scoped pool.
    """
    global _GLOBAL_POOL
    previous = _GLOBAL_POOL
    _GLOBAL_POOL = pool
    return previous


def get_pool() -> PgPool:
    """Return the initialised pool, raising if startup wasn't run."""
    if _GLOBAL_POOL is None:
        raise RuntimeError(
            "Auth pgshim pool not initialised. Call init_pool() during app startup."
        )
    return _GLOBAL_POOL


async def close_pool() -> None:
    global _GLOBAL_POOL
    if _GLOBAL_POOL is not None:
        await _GLOBAL_POOL.close()
        _GLOBAL_POOL = None
