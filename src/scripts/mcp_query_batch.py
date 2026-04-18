"""Batch MCP query runner for ContextGraph (SSE transport).

Reads a JSONL file where each line is one query item:
    {"tool":"find_symbol","arguments":{"name":"IndexPipeline","limit":5}}

If tool is omitted, defaults to find_symbol.
If arguments are omitted, a fallback is generated from the line using key `query`.

Usage:
    python src/scripts/mcp_query_batch.py \
      --base-url http://127.0.0.1:8011 \
      --input docs/mcp-query-batch.sample.jsonl \
      --output docs/mcp-query-batch.result.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx


def _read_message_endpoint(base_url: str, timeout: float = 10.0) -> str:
    sse_url = f"{base_url.rstrip('/')}/mcp/sse"
    with httpx.stream("GET", sse_url, timeout=timeout) as resp:
        resp.raise_for_status()
        data_lines: list[str] = []
        for raw_line in resp.iter_lines():
            if raw_line is None:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
            elif line == "" and data_lines:
                payload = "\n".join(data_lines)
                data_lines.clear()
                if payload.startswith("http://") or payload.startswith("https://") or payload.startswith("/"):
                    if payload.startswith("/"):
                        return f"{base_url.rstrip('/')}{payload}"
                    return payload
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for key in ("endpoint", "message_endpoint", "messages", "url"):
                    endpoint = obj.get(key)
                    if isinstance(endpoint, str):
                        if endpoint.startswith("/"):
                            return f"{base_url.rstrip('/')}{endpoint}"
                        return endpoint
        raise RuntimeError("Did not receive a message endpoint from SSE stream")


def _rpc_call(endpoint: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params,
    }
    resp = httpx.post(endpoint, json=payload, timeout=30.0)
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    if resp.status_code >= 400:
        return {
            "ok": False,
            "http_status": resp.status_code,
            "error": body,
        }
    if isinstance(body, dict) and "error" in body:
        return {"ok": False, "error": body["error"]}
    return {"ok": True, "result": body}


def _prepare_item(obj: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tool = str(obj.get("tool") or "find_symbol")
    arguments = obj.get("arguments")
    if isinstance(arguments, dict):
        return tool, arguments

    query = obj.get("query")
    if tool == "find_symbol":
        return tool, {"name": str(query or ""), "limit": 5}
    if tool == "retrieve_context":
        return tool, {"query": str(query or ""), "limit": 5}
    return tool, {}


def run_batch(base_url: str, input_path: Path, output_path: Path) -> dict[str, Any]:
    endpoint = _read_message_endpoint(base_url)
    started = time.time()

    total = 0
    ok_count = 0
    fail_count = 0

    with input_path.open("r", encoding="utf-8") as src, output_path.open("w", encoding="utf-8") as out:
        for line_no, raw in enumerate(src, start=1):
            raw = raw.strip()
            if not raw:
                continue
            total += 1
            try:
                obj = json.loads(raw)
                if not isinstance(obj, dict):
                    raise ValueError("JSON line must be an object")
            except Exception as exc:
                fail_count += 1
                out.write(json.dumps({
                    "line": line_no,
                    "ok": False,
                    "error": f"invalid_input: {exc}",
                    "raw": raw,
                }, ensure_ascii=True) + "\n")
                continue

            tool, arguments = _prepare_item(obj)
            response = _rpc_call(endpoint, "tools/call", {"name": tool, "arguments": arguments})

            if response.get("ok"):
                ok_count += 1
            else:
                fail_count += 1

            out.write(json.dumps({
                "line": line_no,
                "tool": tool,
                "arguments": arguments,
                **response,
            }, ensure_ascii=True) + "\n")

    return {
        "endpoint": endpoint,
        "total": total,
        "ok": ok_count,
        "failed": fail_count,
        "duration_sec": round(time.time() - started, 3),
        "output": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch MCP query runner")
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--input", required=True, help="Input JSONL path")
    parser.add_argument("--output", default="mcp_batch_output.jsonl", help="Output JSONL path")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    summary = run_batch(args.base_url, input_path, output_path)
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
