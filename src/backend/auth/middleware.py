"""Pure-ASGI middleware: validate Bearer project tokens on /mcp paths.

Uses a pure ASGI class (not BaseHTTPMiddleware) so that ContextVar values
set here propagate correctly into route handlers and MCP tool functions.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import aiosqlite
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.auth.database import DB_PATH
from backend.auth.security import hash_token

if TYPE_CHECKING:
    pass

# Paths that require project-token authentication
_PROTECTED_PREFIXES = ("/mcp",)


async def _send_error(send: Send, body: dict, status: int) -> None:
    data = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(data)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": data, "more_body": False})


class ProjectTokenMiddleware:
    """Pure ASGI middleware that validates MCP Bearer tokens per-project."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not any(path.startswith(p) for p in _PROTECTED_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Parse headers from ASGI scope
        raw_headers: dict[bytes, bytes] = {}
        for name, value in scope.get("headers", []):
            raw_headers[name.lower()] = value

        auth = raw_headers.get(b"authorization", b"").decode()
        if not auth.startswith("Bearer "):
            await _send_error(send, {"detail": "Missing Bearer token"}, 401)
            return

        project_id_raw = raw_headers.get(b"x-project-id", b"").decode()
        if not project_id_raw:
            qs = scope.get("query_string", b"").decode()
            params = {
                k: v
                for part in qs.split("&")
                if "=" in part
                for k, v in [part.split("=", 1)]
            }
            project_id_raw = params.get("project_id", "")

        project_id = project_id_raw.strip()
        if not project_id:
            await _send_error(
                send, {"detail": "Missing project_id (use X-Project-ID header)"}, 401
            )
            return

        token = auth[len("Bearer "):]

        # Validate token against DB
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                digest = hash_token(token)
                async with db.execute(
                    """
                    SELECT pt.id, pt.project_id, pt.token_type,
                           p.project_id AS project_external_id,
                           p.project_name
                    FROM project_tokens pt
                    JOIN projects p ON p.id = pt.project_id
                    WHERE pt.token_hash = ? AND pt.is_active = 1 AND p.is_active = 1
                    """,
                    (digest,),
                ) as cur:
                    row = await cur.fetchone()
        except Exception:
            row = None

        if not row:
            await _send_error(send, {"detail": "Invalid token"}, 401)
            return

        if row["token_type"] != "mcp":
            await _send_error(
                send, {"detail": "Token type not allowed for MCP endpoint"}, 403
            )
            return

        if row["project_external_id"] != project_id:
            await _send_error(
                send, {"detail": "Token is not valid for this project_id"}, 403
            )
            return

        # Store auth context in ASGI scope state (readable via request.state)
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["project_id"] = row["project_external_id"]
        scope["state"]["project_db_id"] = row["project_id"]
        scope["state"]["project_name"] = row["project_name"]
        scope["state"]["project_token_id"] = row["id"]

        # Set ContextVar so MCP tool functions pick up the right project graph.
        # Pure ASGI middleware propagates ContextVars correctly (unlike BaseHTTPMiddleware).
        from backend.graph.registry import _current_project_name

        token_var = _current_project_name.set(row["project_name"])
        try:
            await self.app(scope, receive, send)
        finally:
            _current_project_name.reset(token_var)
