"""Minimal MCP client example for querying ContextGraph over SSE transport.

What this script does:
1. Connects to /mcp/sse and reads the first endpoint payload.
2. Extracts a message endpoint that includes session_id.
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
import json
import os
import sys
import uuid
from typing import Any

import httpx


def _auth_headers(token: str | None, project_id: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if project_id:
        headers["X-Project-ID"] = project_id
    return headers


def _read_message_endpoint(base_url: str, headers: dict[str, str], timeout: float = 10.0) -> str:
    sse_url = f"{base_url.rstrip('/')}/mcp/sse"
    with httpx.stream("GET", sse_url, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        data_lines: list[str] = []
        for raw_line in resp.iter_lines():
            if raw_line is None:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
            # Blank line marks end of one SSE event.
            elif line == "" and data_lines:
                payload = "\n".join(data_lines)
                data_lines.clear()
                # FastMCP SSE usually emits a URL endpoint in first payload.
                if payload.startswith("http://") or payload.startswith("https://") or payload.startswith("/"):
                    if payload.startswith("/"):
                        return f"{base_url.rstrip('/')}{payload}"
                    return payload
                # If JSON format is returned, try common keys.
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for key in ("endpoint", "message_endpoint", "messages", "url"):
                    if key in obj and isinstance(obj[key], str):
                        endpoint = obj[key]
                        if endpoint.startswith("/"):
                            return f"{base_url.rstrip('/')}{endpoint}"
                        return endpoint
        raise RuntimeError("Did not receive a message endpoint from SSE stream")


def _rpc_call(endpoint: str, method: str, params: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }
    resp = httpx.post(endpoint, json=payload, headers=headers, timeout=20.0)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"MCP error: {body['error']}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description="Query CGA MCP server")
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--name", default="IndexPipeline", help="Symbol name to query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--token", default=os.getenv("CONTEXTGRAPH_MCP_TOKEN"))
    parser.add_argument("--project-id", default=os.getenv("CONTEXTGRAPH_PROJECT_ID"))
    args = parser.parse_args()

    headers = _auth_headers(args.token, args.project_id)
    endpoint = _read_message_endpoint(args.base_url, headers)
    print(f"[mcp] message endpoint: {endpoint}")

    result = _rpc_call(
        endpoint,
        "tools/call",
        {
            "name": "find_symbol",
            "arguments": {"name": args.name, "limit": args.limit},
        },
        headers,
    )

    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
