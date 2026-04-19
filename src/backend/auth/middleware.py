"""Starlette middleware: validate Bearer project tokens on /mcp paths."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.auth.database import DB_PATH
from backend.auth.security import hash_token

import aiosqlite

# Paths that require project-token authentication
_PROTECTED_PREFIXES = ("/mcp",)


class ProjectTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not any(request.url.path.startswith(p) for p in _PROTECTED_PREFIXES):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"detail": "Missing Bearer token"}, status_code=401)

        project_id_raw = request.headers.get("X-Project-ID") or request.query_params.get("project_id")
        if not project_id_raw:
            return JSONResponse({"detail": "Missing project_id (use X-Project-ID header)"}, status_code=401)

        try:
            project_id = int(project_id_raw)
        except ValueError:
            return JSONResponse({"detail": "Invalid project_id"}, status_code=400)

        token = auth[len("Bearer "):]

        # Check project token table + active project
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                digest = hash_token(token)
                async with db.execute(
                    """
                    SELECT pt.id, pt.project_id, pt.token_type
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
            return JSONResponse({"detail": "Invalid token"}, status_code=401)

        if row["token_type"] != "mcp":
            return JSONResponse({"detail": "Token type not allowed for MCP endpoint"}, status_code=403)

        if row["project_id"] != project_id:
            return JSONResponse({"detail": "Token is not valid for this project_id"}, status_code=403)

        request.state.project_id = row["project_id"]
        request.state.project_token_id = row["id"]

        return await call_next(request)
