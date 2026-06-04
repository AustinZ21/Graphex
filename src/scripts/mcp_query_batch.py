"""Batch MCP query runner for ContextGraph (SSE transport).

Reads a JSONL file where each line is one query item:
    {"tool":"find_symbol","arguments":{"name":"IndexPipeline","limit":5}}

If tool is omitted, defaults to find_symbol.
If arguments are omitted, a fallback is generated from the line using key `query`.

Usage:
    set CONTEXTGRAPH_MCP_TOKEN=<project-token>
    set CONTEXTGRAPH_PROJECT_ID=<project-id>
    python src/scripts/mcp_query_batch.py \
      --base-url http://127.0.0.1:8011 \
      --input docs/mcp-query-batch.sample.jsonl \
      --output docs/mcp-query-batch.result.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import timedelta
from pathlib import Path
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


async def _mcp_tool_call(
    session: ClientSession,
    tool: str,
    arguments: dict[str, Any],
    request_timeout_sec: float,
) -> dict[str, Any]:
    result = await session.call_tool(
        tool,
        arguments,
        read_timeout_seconds=timedelta(seconds=request_timeout_sec),
    )
    payload = _tool_result_to_json(result)
    if payload.get("isError"):
        return {"ok": False, "error": payload}
    return {"ok": True, "result": payload}


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


async def _call_with_retry(
    session: ClientSession,
    tool: str,
    arguments: dict[str, Any],
    retries: int,
    request_timeout_sec: float,
) -> tuple[dict[str, Any], int]:
    attempts = 0
    while True:
        attempts += 1
        try:
            response = await _mcp_tool_call(session, tool, arguments, request_timeout_sec)
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        if response.get("ok"):
            return response, attempts

        transient = False
        status = response.get("http_status")
        if isinstance(status, int) and status in {408, 429, 500, 502, 503, 504}:
            transient = True
        if isinstance(response.get("error"), dict) and "raw" in response.get("error", {}):
            transient = True

        if transient and attempts <= retries + 1:
            await asyncio.sleep(min(0.25 * attempts, 1.5))
            continue
        return response, attempts


def _extract_failed_items(output_path: Path) -> list[dict[str, Any]]:
    """Extract failed items from output JSONL (ok==False)."""
    failed: list[dict[str, Any]] = []
    if not output_path.exists():
        return failed
    with output_path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                if not obj.get("ok") and not obj.get("cancelled"):
                    failed.append(obj)
            except Exception:
                continue
    return failed


def _reconstruct_input_jsonl(failed_items: list[dict[str, Any]]) -> str:
    """Reconstruct JSONL input format from failed items."""
    lines = []
    for item in failed_items:
        original_line = int(item.get("line", 0) or 0)
        if original_line <= 0:
            continue
        tool = item.get("tool", "find_symbol")
        arguments = item.get("arguments", {})
        query_obj = {"tool": tool, "arguments": arguments, "__line": original_line}
        lines.append(json.dumps(query_obj, ensure_ascii=True))
    return "\n".join(lines)


def _load_previous_results(output_path: Path, resume_from_output: bool) -> dict[int, dict[str, Any]]:
    previous_results: dict[int, dict[str, Any]] = {}
    if not resume_from_output or not output_path.exists():
        return previous_results

    with output_path.open("r", encoding="utf-8") as prev:
        for raw in prev:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                line_no = int(obj.get("line"))
                previous_results[line_no] = obj
            except Exception:
                continue
    return previous_results


def _load_tasks(
    input_path: Path,
    previous_results: dict[int, dict[str, Any]],
    retry_failed_from_resume: bool,
) -> list[tuple[int, str, dict[str, Any], str]]:
    tasks: list[tuple[int, str, dict[str, Any], str]] = []
    with input_path.open("r", encoding="utf-8") as src:
        for source_line_no, raw in enumerate(src, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                if not isinstance(obj, dict):
                    raise ValueError("JSON line must be an object")

                line_no = int(obj.get("__line") or source_line_no)
                if line_no in previous_results:
                    prev = previous_results[line_no]
                    should_retry = retry_failed_from_resume and not bool(prev.get("ok"))
                    if should_retry:
                        previous_results.pop(line_no, None)
                    else:
                        continue

                tool, arguments = _prepare_item(obj)
                tasks.append((line_no, tool, arguments, raw))
            except Exception:
                line_no = source_line_no
                if line_no in previous_results:
                    continue
                tasks.append((line_no, "", {}, raw))
    return tasks


async def run_batch(
    base_url: str,
    input_path: Path,
    output_path: Path,
    concurrency: int,
    retries: int,
    request_timeout_sec: float,
    fail_fast: bool,
    max_errors: int,
    resume_from_output: bool,
    token: str | None = None,
    project_id: str | None = None,
    retry_failed_from_resume: bool = False,
) -> dict[str, Any]:
    headers = _auth_headers(token, project_id)
    endpoint = f"{base_url.rstrip('/')}/mcp/sse"
    started = time.time()

    previous_results = _load_previous_results(output_path, resume_from_output)
    tasks = _load_tasks(input_path, previous_results, retry_failed_from_resume)
    total = len(tasks) + len(previous_results)

    ok_count = 0
    fail_count = 0
    retry_count = 0
    cancelled_count = 0
    results: list[dict[str, Any]] = []

    semaphore = asyncio.Semaphore(max(1, concurrency))
    stop_event = asyncio.Event()

    async with sse_client(
        endpoint,
        headers=headers,
        timeout=request_timeout_sec,
        sse_read_timeout=max(60.0, request_timeout_sec),
    ) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            async def worker(item: tuple[int, str, dict[str, Any], str]) -> dict[str, Any]:
                line_no, tool, arguments, raw = item

                if stop_event.is_set():
                    return {
                        "line": line_no,
                        "ok": False,
                        "cancelled": True,
                        "error": "cancelled: fail-fast or max-errors reached",
                    }

                if not tool:
                    return {
                        "line": line_no,
                        "ok": False,
                        "error": "invalid_input: JSON line must be an object",
                        "raw": raw,
                    }

                async with semaphore:
                    response, attempts = await _call_with_retry(
                        session,
                        tool,
                        arguments,
                        retries=retries,
                        request_timeout_sec=request_timeout_sec,
                    )

                return {
                    "line": line_no,
                    "tool": tool,
                    "arguments": arguments,
                    "attempts": attempts,
                    **response,
                }

            pending = [asyncio.create_task(worker(item)) for item in tasks]
            while pending:
                done, pending_set = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                pending = list(pending_set)

                for task in done:
                    item = task.result()
                    results.append(item)

                    if item.get("cancelled"):
                        continue

                    if not item.get("ok"):
                        fail_count += 1
                        if fail_fast or (max_errors > 0 and fail_count >= max_errors):
                            stop_event.set()

                if stop_event.is_set():
                    for task in pending:
                        task.cancel()
                    if pending:
                        cancelled = await asyncio.gather(*pending, return_exceptions=True)
                        for item in cancelled:
                            if isinstance(item, dict):
                                results.append(item)
                            else:
                                cancelled_count += 1
                    pending = []

    merged_results = list(previous_results.values()) + results
    merged_results.sort(key=lambda x: x["line"])

    with output_path.open("w", encoding="utf-8") as out:
        for item in merged_results:
            if item.get("cancelled"):
                cancelled_count += 1
                out.write(json.dumps(item, ensure_ascii=True) + "\n")
                continue
            if item.get("ok"):
                ok_count += 1
            attempts = int(item.get("attempts", 1))
            if attempts > 1:
                retry_count += attempts - 1
            out.write(json.dumps(item, ensure_ascii=True) + "\n")

    duration_sec = time.time() - started
    qps = round(total / duration_sec, 3) if duration_sec > 0 else 0.0

    return {
        "endpoint": endpoint,
        "total": total,
        "resumed_skipped": len(previous_results),
        "executed_now": len(tasks),
        "ok": ok_count,
        "failed": fail_count,
        "cancelled": cancelled_count,
        "retries": retry_count,
        "concurrency": max(1, concurrency),
        "fail_fast": fail_fast,
        "max_errors": max_errors,
        "resume_from_output": resume_from_output,
        "duration_sec": round(duration_sec, 3),
        "qps": qps,
        "output": str(output_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch MCP query runner")
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--input", required=True, help="Input JSONL path")
    parser.add_argument("--output", default="mcp_batch_output.jsonl", help="Output JSONL path")
    parser.add_argument("--concurrency", type=int, default=4, help="Max in-flight MCP calls")
    parser.add_argument("--retries", type=int, default=1, help="Retries for transient failures")
    parser.add_argument("--request-timeout-sec", type=float, default=30.0, help="Per-request timeout")
    parser.add_argument("--fail-fast", action="store_true", help="Stop scheduling once first error is seen")
    parser.add_argument("--max-errors", type=int, default=0, help="Stop when failures reach this number (0=disabled)")
    parser.add_argument("--resume-from-output", action="store_true", help="Reuse existing output file and skip already completed line numbers")
    parser.add_argument("--only-failed-from-output", action="store_true", help="Extract failed items from output file and retry only those queries")
    parser.add_argument("--token", default=os.getenv("CONTEXTGRAPH_MCP_TOKEN"))
    parser.add_argument("--project-id", default=os.getenv("CONTEXTGRAPH_PROJECT_ID"))
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    effective_input_path = input_path
    temp_input_path: Path | None = None
    if args.only_failed_from_output:
        failed_items = _extract_failed_items(output_path)
        if not failed_items:
            print(json.dumps({"message": "No failed items found in output file", "output": str(output_path)}, indent=2, ensure_ascii=True))
            return 0
        reconstructed = _reconstruct_input_jsonl(failed_items)
        temp_input_path = Path(f".mcp_batch_failed_items_{int(time.time())}.jsonl")
        temp_input_path.write_text(reconstructed, encoding="utf-8")
        effective_input_path = temp_input_path
        print(f"Retrying {len(failed_items)} failed items from {output_path}")

    try:
        summary = asyncio.run(
            run_batch(
                args.base_url,
                effective_input_path,
                output_path,
                concurrency=args.concurrency,
                retries=args.retries,
                request_timeout_sec=args.request_timeout_sec,
                fail_fast=args.fail_fast,
                max_errors=max(0, args.max_errors),
                resume_from_output=args.resume_from_output or args.only_failed_from_output,
                token=args.token,
                project_id=args.project_id,
                retry_failed_from_resume=args.only_failed_from_output,
            )
        )
        print(json.dumps(summary, indent=2, ensure_ascii=True))
        return 0
    finally:
        if temp_input_path and temp_input_path.exists():
            temp_input_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())