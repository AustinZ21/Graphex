"""Minimal MCP client example for querying ContextGraph over SSE transport.

What this script does:
1. Connects to /mcp/sse and keeps the SSE session open.
2. Initializes the MCP session.
3. Sends a tools/call request for find_symbol.

Usage:
    set CONTEXTGRAPH_MCP_TOKEN=<project-token>
    set CONTEXTGRAPH_PROJECT_ID=<project-id>
    python src/scripts/mcp_query_example.py --base-url http://127.0.0.1:8011 --name IndexPipeline

Notes:
- This script is intentionally minimal and synchronous.
- It assumes the server exposes the SSE MCP transport under /mcp/sse.
- It reads MCP credentials from environment variables unless --token and --project-id are provided.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client


def _auth_headers(token: str | None, project_id: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if project_id:
        headers["X-Project-ID"] = project_id
    return headers


def _tool_result_to_json(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return {"result": str(result)}


async def _call_find_symbol(base_url: str, headers: dict[str, str], name: str, limit: int) -> dict[str, Any]:
    async with sse_client(
        f"{base_url.rstrip('/')}/mcp/sse",
        headers=headers,
        timeout=20,
        sse_read_timeout=60,
    ) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool("find_symbol", {"name": name, "limit": limit})
    return _tool_result_to_json(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Query CGA MCP server")
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--name", default="IndexPipeline", help="Symbol name to query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--token", default=os.getenv("CONTEXTGRAPH_MCP_TOKEN"))
    parser.add_argument("--project-id", default=os.getenv("CONTEXTGRAPH_PROJECT_ID"))
    args = parser.parse_args()

    headers = _auth_headers(args.token, args.project_id)
    result = asyncio.run(_call_find_symbol(args.base_url, headers, args.name, args.limit))

    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
