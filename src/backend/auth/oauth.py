"""OAuth connection storage and refresh helpers for user-owned integrations."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken

from backend.auth.pgshim import Connection
from backend.auth.security import JWT_SECRET


TOKEN_REFRESH_MARGIN = timedelta(minutes=5)


@dataclass(frozen=True)
class OAuthConnection:
    id: int
    user_id: int
    provider: str
    account_id: str
    display_name: str
    scope: str
    token_cache: dict[str, Any]
    expires_at: datetime | None
    created_at: str
    updated_at: str
    is_active: bool


@dataclass(frozen=True)
class AccessTokenResult:
    status: str
    access_token: str | None = None
    expires_at: datetime | None = None
    detail: str | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _encryption_key() -> bytes:
    configured = os.getenv("CGA_OAUTH_TOKEN_KEY", "").strip()
    if configured:
        try:
            raw = base64.urlsafe_b64decode(configured.encode())
            if len(raw) == 32:
                return configured.encode()
        except Exception:
            pass
        return base64.urlsafe_b64encode(hashlib.sha256(configured.encode()).digest())

    secret = os.getenv("JWT_SECRET_KEY", JWT_SECRET)
    return base64.urlsafe_b64encode(hashlib.sha256(f"cga-oauth:{secret}".encode()).digest())


def _fernet() -> Fernet:
    return Fernet(_encryption_key())


def encrypt_token_cache(cache: dict[str, Any]) -> str:
    payload = json.dumps(cache, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return _fernet().encrypt(payload).decode()


def decrypt_token_cache(value: str) -> dict[str, Any]:
    try:
        raw = _fernet().decrypt(value.encode())
    except InvalidToken as exc:
        raise ValueError("OAuth token cache cannot be decrypted") from exc
    data = json.loads(raw.decode())
    if not isinstance(data, dict):
        raise ValueError("OAuth token cache payload is invalid")
    return data


def normalize_token_response(
    token_data: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous or {}
    now = utc_now()
    expires_in = int(token_data.get("expires_in") or previous.get("expires_in") or 3600)
    expires_at = now + timedelta(seconds=max(60, expires_in))
    refresh_token = token_data.get("refresh_token") or previous.get("refresh_token")
    cache = {
        "access_token": token_data.get("access_token") or previous.get("access_token"),
        "refresh_token": refresh_token,
        "token_type": token_data.get("token_type") or previous.get("token_type") or "Bearer",
        "scope": token_data.get("scope") or previous.get("scope") or "",
        "expires_in": expires_in,
        "expires_at": format_datetime(expires_at),
        "obtained_at": format_datetime(now),
    }
    if token_data.get("id_token"):
        cache["id_token"] = token_data["id_token"]
    return {k: v for k, v in cache.items() if v not in (None, "")}


def token_cache_expires_at(cache: dict[str, Any]) -> datetime | None:
    return parse_datetime(cache.get("expires_at"))


async def upsert_oauth_connection(
    db: Connection,
    *,
    user_id: int,
    provider: str,
    account_id: str,
    display_name: str,
    scope: str,
    token_cache: dict[str, Any],
) -> OAuthConnection:
    provider = provider.strip().lower()
    account_id = account_id.strip() or "default"
    display_name = display_name.strip() or account_id
    encrypted = encrypt_token_cache(token_cache)
    now_s = format_datetime(utc_now()) or ""
    expires_at = format_datetime(token_cache_expires_at(token_cache))

    async with db.execute(
        """
        INSERT INTO oauth_connections(
            user_id, provider, account_id, display_name, scope,
            token_cache_enc, expires_at, created_at, updated_at, is_active
        ) VALUES(?,?,?,?,?,?,?,?,?,1)
        ON CONFLICT(user_id, provider, account_id) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            scope = EXCLUDED.scope,
            token_cache_enc = EXCLUDED.token_cache_enc,
            expires_at = EXCLUDED.expires_at,
            updated_at = EXCLUDED.updated_at,
            is_active = 1
        RETURNING id, user_id, provider, account_id, display_name, scope,
                  token_cache_enc, expires_at, created_at, updated_at, is_active
        """,
        (user_id, provider, account_id, display_name, scope, encrypted, expires_at, now_s, now_s),
    ) as cur:
        row = await cur.fetchone()
    await db.commit()
    return _connection_from_row(row)


async def get_oauth_connection(
    db: Connection,
    *,
    user_id: int,
    provider: str,
) -> OAuthConnection | None:
    async with db.execute(
        """
        SELECT id, user_id, provider, account_id, display_name, scope,
               token_cache_enc, expires_at, created_at, updated_at, is_active
        FROM oauth_connections
        WHERE user_id = ? AND provider = ? AND is_active = 1
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, provider.strip().lower()),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return _connection_from_row(row)


async def get_oauth_connection_status(
    db: Connection,
    *,
    user_id: int,
    provider: str,
) -> dict[str, Any]:
    connection = await get_oauth_connection(db, user_id=user_id, provider=provider)
    if not connection:
        return {"connected": False, "provider": provider}
    return {
        "connected": True,
        "provider": connection.provider,
        "account_id": connection.account_id,
        "display_name": connection.display_name,
        "scope": connection.scope,
        "expires_at": format_datetime(connection.expires_at),
        "updated_at": connection.updated_at,
    }


async def deactivate_oauth_connection(
    db: Connection,
    *,
    user_id: int,
    provider: str,
) -> None:
    await db.execute(
        "UPDATE oauth_connections SET is_active = 0, updated_at = ? WHERE user_id = ? AND provider = ?",
        (format_datetime(utc_now()), user_id, provider.strip().lower()),
    )
    await db.commit()


async def get_valid_access_token(
    db: Connection,
    *,
    user_id: int,
    provider: str,
    client_id: str,
    token_url: str,
    scope: str,
) -> AccessTokenResult:
    connection = await get_oauth_connection(db, user_id=user_id, provider=provider)
    if not connection:
        return AccessTokenResult(status="not_connected", detail="No OAuth connection found")

    cache = dict(connection.token_cache)
    expires_at = token_cache_expires_at(cache)
    access_token = cache.get("access_token")
    if access_token and expires_at and expires_at - TOKEN_REFRESH_MARGIN > utc_now():
        return AccessTokenResult(status="ok", access_token=str(access_token), expires_at=expires_at)

    refresh_token = cache.get("refresh_token")
    if not refresh_token:
        return AccessTokenResult(status="reauth_required", detail="OAuth refresh token is missing")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                token_url,
                data={
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": scope,
                },
            )
    except httpx.HTTPError as exc:
        return AccessTokenResult(status="refresh_failed", detail=str(exc))

    if response.status_code >= 400:
        return AccessTokenResult(status="reauth_required", detail=_oauth_error_detail(response))

    next_cache = normalize_token_response(response.json(), previous=cache)
    await upsert_oauth_connection(
        db,
        user_id=user_id,
        provider=connection.provider,
        account_id=connection.account_id,
        display_name=connection.display_name,
        scope=scope,
        token_cache=next_cache,
    )
    next_expires_at = token_cache_expires_at(next_cache)
    return AccessTokenResult(
        status="ok",
        access_token=str(next_cache.get("access_token") or ""),
        expires_at=next_expires_at,
    )


def _oauth_error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        return response.text[:500]
    if isinstance(data, dict):
        return str(data.get("error_description") or data.get("error") or response.status_code)
    return str(response.status_code)


def _connection_from_row(row: Any) -> OAuthConnection:
    if row is None:
        raise ValueError("OAuth connection row is missing")
    token_cache = decrypt_token_cache(row["token_cache_enc"])
    return OAuthConnection(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        provider=str(row["provider"]),
        account_id=str(row["account_id"]),
        display_name=str(row["display_name"] or ""),
        scope=str(row["scope"] or ""),
        token_cache=token_cache,
        expires_at=parse_datetime(row["expires_at"]),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        is_active=bool(row["is_active"]),
    )