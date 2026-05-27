"""Shared pytest fixtures for CGA tests."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, Generator

import asyncpg
import pytest
import pytest_asyncio

from backend.auth import pgshim as auth_pgshim
from backend.auth.database import _CREATE_TABLES as _AUTH_CREATE_TABLES
from backend.workbriefing.store import PgVectorActivityStore, resolve_dsn

WORKBRIEFING_TEST_DSN_ENV = "WORKBRIEFING_TEST_POSTGRES_DSN"
AUTH_TEST_DSN_ENV = "AUTH_TEST_POSTGRES_DSN"
DEFAULT_TEST_DSN = "postgresql://app:app@localhost:15432/appdb"


def _resolve_test_dsn() -> str:
    return os.getenv(WORKBRIEFING_TEST_DSN_ENV) or os.getenv("WORKBRIEFING_POSTGRES_DSN") or DEFAULT_TEST_DSN


async def _probe_dsn(dsn: str) -> str | None:
    try:
        conn = await asyncpg.connect(dsn=dsn, timeout=2.0)
    except Exception as exc:  # pragma: no cover - host environment dependent
        return str(exc)
    try:
        await conn.execute("SELECT 1;")
    finally:
        await conn.close()
    return None


@pytest.fixture(scope="session")
def workbriefing_pg_dsn() -> str:
    dsn = _resolve_test_dsn()
    error = asyncio.run(_probe_dsn(dsn))
    if error is not None:
        pytest.skip(
            f"WorkBriefing pgvector Postgres not reachable at {dsn!r}: {error}. "
            f"Set {WORKBRIEFING_TEST_DSN_ENV} or start the docker compose postgres service."
        )
    return dsn


@pytest_asyncio.fixture
async def pg_activity_store(workbriefing_pg_dsn: str) -> AsyncGenerator[PgVectorActivityStore, None]:
    """Per-test PgVectorActivityStore bound to a unique throwaway schema."""
    schema = f"wb_test_{uuid.uuid4().hex[:12]}"
    store = PgVectorActivityStore(dsn=workbriefing_pg_dsn, schema=schema)
    try:
        await store.ensure_schema()
        yield store
    finally:
        try:
            pool = await store._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
        finally:
            await store.close()


@pytest.fixture
def make_pg_activity_store(workbriefing_pg_dsn: str) -> Generator[callable, None, None]:
    """Factory that yields fresh PgVectorActivityStore instances pointing to one shared schema.

    Useful for tests that need to construct multiple stores against the same data
    (e.g. simulating two service instances sharing storage).
    """
    schema = f"wb_test_{uuid.uuid4().hex[:12]}"
    created: list[PgVectorActivityStore] = []

    def _factory() -> PgVectorActivityStore:
        store = PgVectorActivityStore(dsn=workbriefing_pg_dsn, schema=schema)
        created.append(store)
        return store

    try:
        yield _factory
    finally:
        async def _cleanup() -> None:
            cleanup_store = PgVectorActivityStore(dsn=workbriefing_pg_dsn, schema=schema)
            try:
                pool = await cleanup_store._get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
            finally:
                await cleanup_store.close()
                for store in created:
                    try:
                        await store.close()
                    except Exception:
                        pass

        asyncio.run(_cleanup())


def _resolve_auth_test_dsn() -> str:
    return os.getenv(AUTH_TEST_DSN_ENV) or os.getenv("CGA_POSTGRES_DSN") or DEFAULT_TEST_DSN


@pytest.fixture(scope="session")
def auth_pg_dsn() -> str:
    dsn = _resolve_auth_test_dsn()
    error = asyncio.run(_probe_dsn(dsn))
    if error is not None:
        pytest.skip(
            f"Auth Postgres not reachable at {dsn!r}: {error}. "
            f"Set {AUTH_TEST_DSN_ENV} or start the docker compose postgres service."
        )
    return dsn


@pytest_asyncio.fixture
async def auth_pg_pool(auth_pg_dsn: str) -> AsyncGenerator[auth_pgshim.PgPool, None]:
    """Per-test auth pgshim pool pinned to a unique throwaway schema.

    The pool is installed as the process-wide pgshim pool for the duration of
    the test, so any code path that calls :func:`pgshim.get_pool` (router,
    middleware, etc.) operates against the isolated schema.
    """
    schema = f"auth_test_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(dsn=auth_pg_dsn)
    try:
        await admin.execute(f'CREATE SCHEMA "{schema}";')
    finally:
        await admin.close()

    pool = auth_pgshim.PgPool(
        auth_pg_dsn,
        server_settings={"search_path": schema},
    )
    await pool.open()
    previous = auth_pgshim.set_pool(pool)

    # Create the auth tables (users / projects / project_tokens / audit_logs)
    # inside the per-test schema using the same DDL the production startup
    # path runs.
    async with pool.acquire() as db:
        await db.executescript(_AUTH_CREATE_TABLES)

    try:
        yield pool
    finally:
        auth_pgshim.set_pool(previous)
        await pool.close()
        cleanup = await asyncpg.connect(dsn=auth_pg_dsn)
        try:
            await cleanup.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
        finally:
            await cleanup.close()
