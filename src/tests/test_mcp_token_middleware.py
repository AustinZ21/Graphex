from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from backend.auth.middleware import ProjectTokenMiddleware
from backend.auth.crystals import crystal_suite_headers
from backend.auth.security import hash_token


async def _seed_db(pool) -> None:
    async with pool.acquire() as db:
        await db.execute(
            "INSERT INTO projects(id, project_name, project_id, is_active) "
            "VALUES (?, ?, ?, 1)",
            (1, "p1", "P1"),
        )
        await db.execute(
            "INSERT INTO projects(id, project_name, project_id, is_active) "
            "VALUES (?, ?, ?, 1)",
            (2, "p2", "P2"),
        )
        await db.execute(
            "INSERT INTO project_tokens(project_id, token_type, token_hash, "
            "token_hint, is_active) VALUES (?, ?, ?, ?, 1)",
            (1, "mcp", hash_token("good-token"), "goodtok..."),
        )
        await db.execute(
            "INSERT INTO project_tokens(project_id, token_type, token_hash, "
            "token_hint, is_active) VALUES (?, ?, ?, ?, 1)",
            (1, "legacy", hash_token("legacy-token"), "legacy..."),
        )


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ProjectTokenMiddleware)

    @app.get("/mcp")
    async def mcp_discovery() -> dict:
        return {"transport": "sse", "sse_endpoint": "/mcp/sse"}

    @app.get("/mcp/ping")
    async def ping() -> dict:
        return {"ok": True}

    @app.get("/api/project/ping")
    async def project_ping(request: Request) -> dict:
        return {
            "ok": True,
            "project_id": getattr(request.state, "project_id", None),
            "project_name": getattr(request.state, "project_name", None),
            "project_token_type": getattr(request.state, "project_token_type", None),
        }

    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _crystal_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = crystal_suite_headers()
    if extra:
        headers.update(extra)
    return headers


@pytest.mark.asyncio
async def test_mcp_discovery_is_public(auth_pg_pool):
    await _seed_db(auth_pg_pool)
    async with _client(_build_app()) as client:
        resp = await client.get("/mcp")

    assert resp.status_code == 200
    assert resp.json() == {"transport": "sse", "sse_endpoint": "/mcp/sse"}


@pytest.mark.asyncio
async def test_mcp_rejects_missing_project_id(auth_pg_pool):
    await _seed_db(auth_pg_pool)
    async with _client(_build_app()) as client:
        resp = await client.get(
            "/mcp/ping", headers=_crystal_headers({"Authorization": "Bearer good-token"})
        )

    assert resp.status_code == 401
    assert "Missing project_id" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_mcp_rejects_missing_crystals_profile(auth_pg_pool):
    await _seed_db(auth_pg_pool)
    async with _client(_build_app()) as client:
        resp = await client.get(
            "/mcp/ping",
            headers={
                "Authorization": "Bearer good-token",
                "X-Project-ID": "P1",
            },
        )

    assert resp.status_code == 426
    assert "CRYSTALS" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_mcp_rejects_non_mcp_token_type(auth_pg_pool):
    await _seed_db(auth_pg_pool)
    async with _client(_build_app()) as client:
        resp = await client.get(
            "/mcp/ping",
            headers=_crystal_headers({
                "Authorization": "Bearer legacy-token",
                "X-Project-ID": "P1",
            }),
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Token type not allowed for MCP endpoint"


@pytest.mark.asyncio
async def test_mcp_rejects_project_mismatch(auth_pg_pool):
    await _seed_db(auth_pg_pool)
    async with _client(_build_app()) as client:
        resp = await client.get(
            "/mcp/ping",
            headers=_crystal_headers({
                "Authorization": "Bearer good-token",
                "X-Project-ID": "P2",
            }),
        )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Token is not valid for this project_id"


@pytest.mark.asyncio
async def test_mcp_accepts_matching_mcp_token(auth_pg_pool):
    await _seed_db(auth_pg_pool)
    async with _client(_build_app()) as client:
        resp = await client.get(
            "/mcp/ping",
            headers=_crystal_headers({
                "Authorization": "Bearer good-token",
                "X-Project-ID": "P1",
            }),
        )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_project_api_accepts_mcp_token_without_explicit_project_id(
    auth_pg_pool,
):
    await _seed_db(auth_pg_pool)
    async with _client(_build_app()) as client:
        resp = await client.get(
            "/api/project/ping",
            headers=_crystal_headers({"Authorization": "Bearer good-token"}),
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "project_id": "P1",
        "project_name": "p1",
        "project_token_type": "mcp",
    }
