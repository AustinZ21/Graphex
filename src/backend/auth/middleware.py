"""Starlette middleware: validate Bearer project tokens on /mcp paths."""
from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.auth.database import DB_PATH
from backend.auth.security import hash_token

import aiosqlite

# Paths that require project-token authentication
_PROTECTED_PREFIXES = ("/mcp",)

# Legacy fallback (agentrouter compat): honour MCP_ACCESS_TOKEN env var too
_LEGACY_TOKEN = os.getenv("MCP_ACCESS_TOKEN", "")


class ProjectTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not any(request.url.path.startswith(p) for p in _PROTECTED_PREFIXES):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"detail": "Missing Bearer token"}, status_code=401)

        token = auth[len("Bearer "):]

        # 1. Check legacy env-var token (no DB round-trip needed)
        if _LEGACY_TOKEN and token == _LEGACY_TOKEN:
            return await call_next(request)

        # 2. Check project token table
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                digest = hash_token(token)
                async with db.execute(
                    "SELECT id FROM project_tokens WHERE token_hash = ? AND is_active = 1",
                    (digest,),
                ) as cur:
                    row = await cur.fetchone()
        except Exception:
            row = None

        if not row:
            return JSONResponse({"detail": "Invalid token"}, status_code=401)

        return await call_next(request)
