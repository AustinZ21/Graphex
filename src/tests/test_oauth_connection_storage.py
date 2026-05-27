from __future__ import annotations

import pytest

from backend.auth.oauth import (
    deactivate_oauth_connection,
    decrypt_token_cache,
    get_oauth_connection_status,
    get_valid_access_token,
    normalize_token_response,
    upsert_oauth_connection,
)


@pytest.mark.asyncio
async def test_oauth_connection_stores_encrypted_token_cache(auth_pg_pool, monkeypatch) -> None:
    monkeypatch.setenv("CGA_OAUTH_TOKEN_KEY", "unit-test-oauth-key")
    token_cache = normalize_token_response(
        {
            "access_token": "secret-access-token",
            "refresh_token": "secret-refresh-token",
            "expires_in": 3600,
            "scope": "499b84ac-1321-427f-aa17-267ca6975798/.default offline_access",
        }
    )

    async with auth_pg_pool.acquire() as db:
        await db.execute(
            "INSERT INTO users(id, username, password_hash, role, is_active) VALUES(?,?,?,?,1)",
            (1, "admin", "hash", "admin"),
        )
        connection = await upsert_oauth_connection(
            db,
            user_id=1,
            provider="microsoft",
            account_id="user-oid",
            display_name="Admin User",
            scope=token_cache["scope"],
            token_cache=token_cache,
        )

        async with db.execute("SELECT token_cache_enc FROM oauth_connections WHERE id = ?", (connection.id,)) as cur:
            row = await cur.fetchone()

        status = await get_oauth_connection_status(db, user_id=1, provider="microsoft")

    encrypted = row["token_cache_enc"]
    assert "secret-access-token" not in encrypted
    assert "secret-refresh-token" not in encrypted
    assert decrypt_token_cache(encrypted)["access_token"] == "secret-access-token"
    assert status["connected"] is True
    assert status["display_name"] == "Admin User"


@pytest.mark.asyncio
async def test_get_valid_access_token_uses_cached_fresh_access_token(auth_pg_pool, monkeypatch) -> None:
    monkeypatch.setenv("CGA_OAUTH_TOKEN_KEY", "unit-test-oauth-key")
    token_cache = normalize_token_response(
        {
            "access_token": "fresh-access-token",
            "refresh_token": "fresh-refresh-token",
            "expires_in": 3600,
            "scope": "scope",
        }
    )

    async with auth_pg_pool.acquire() as db:
        await db.execute(
            "INSERT INTO users(id, username, password_hash, role, is_active) VALUES(?,?,?,?,1)",
            (1, "admin", "hash", "admin"),
        )
        await upsert_oauth_connection(
            db,
            user_id=1,
            provider="microsoft",
            account_id="user-oid",
            display_name="Admin User",
            scope="scope",
            token_cache=token_cache,
        )

        result = await get_valid_access_token(
            db,
            user_id=1,
            provider="microsoft",
            client_id="client-id",
            token_url="https://login.microsoftonline.com/organizations/oauth2/v2.0/token",
            scope="scope",
        )

        await deactivate_oauth_connection(db, user_id=1, provider="microsoft")
        disconnected = await get_oauth_connection_status(db, user_id=1, provider="microsoft")

    assert result.status == "ok"
    assert result.access_token == "fresh-access-token"
    assert disconnected["connected"] is False