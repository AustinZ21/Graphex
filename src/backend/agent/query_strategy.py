"""CG-first query strategy for agents.

Strategy:
1. Query ContextGraph MCP first (retrieve_context + call graph).
2. Build compact graph context under a token budget.
3. If graph hits are insufficient, fallback to local code snippets.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


def estimate_tokens(text: str) -> int:
    """Rough token estimate for budget control (4 chars ~= 1 token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def trim_items_to_budget(items: list[dict[str, Any]], budget_tokens: int) -> tuple[list[dict[str, Any]], int]:
    """Keep items in order while respecting token budget."""
    kept: list[dict[str, Any]] = []
    used = 0
    for item in items:
        item_tokens = estimate_tokens(json.dumps(item, ensure_ascii=True))
        if used + item_tokens > budget_tokens:
            break
        kept.append(item)
        used += item_tokens
    return kept, used


def read_code_snippet(
    repo_root: Path,
    relative_path: str,
    line_start: int,
    line_end: int,
    context_lines: int = 3,
    max_chars: int = 1200,
) -> str:
    """Read a bounded code snippet around a symbol location."""
    file_path = (repo_root / relative_path).resolve()
    if not file_path.exists() or not file_path.is_file():
        return ""

    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""

    if not lines:
        return ""

    start_idx = max(0, line_start - 1 - context_lines)
    end_idx = min(len(lines), line_end + context_lines)
    snippet = "\n".join(lines[start_idx:end_idx]).strip()
    if len(snippet) > max_chars:
        return snippet[: max_chars - 3] + "..."
    return snippet


@dataclass
class StrategyConfig:
    base_url: str
    repo_root: Path
    graph_top_k: int = 8
    min_graph_hits: int = 3
    token_budget: int = 1800
    relation_depth: int = 1
    include_relations: bool = True
    fallback_max_files: int = 3
    fallback_context_lines: int = 3


class CGFirstQueryStrategy:
    """ContextGraph-first query strategy with safe local fallback."""

    def __init__(self, config: StrategyConfig) -> None:
        self._cfg = config

    def run(self, query: str) -> dict[str, Any]:
        endpoint = self._read_message_endpoint(self._cfg.base_url)
        graph_hits = self._retrieve_graph_hits(endpoint, query)
        graph_items = self._build_graph_context(endpoint, graph_hits)

        graph_items_trimmed, graph_tokens = trim_items_to_budget(graph_items, self._cfg.token_budget)
        used_fallback = len(graph_items_trimmed) < self._cfg.min_graph_hits

        fallback_items: list[dict[str, Any]] = []
        fallback_tokens = 0
        if used_fallback:
            remaining = max(0, self._cfg.token_budget - graph_tokens)
            fallback_items = self._build_fallback_snippets(query, graph_hits)
            fallback_items, fallback_tokens = trim_items_to_budget(fallback_items, remaining)

        return {
            "strategy": "cg-first",
            "query": query,
            "mcp_base_url": self._cfg.base_url,
            "token_budget": self._cfg.token_budget,
            "estimated_tokens": graph_tokens + fallback_tokens,
            "graph_hits_total": len(graph_hits),
            "graph_context": graph_items_trimmed,
            "used_fallback": used_fallback,
            "fallback_context": fallback_items,
        }

    def _read_message_endpoint(self, base_url: str, timeout: float = 10.0) -> str:
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

    def _rpc_call(self, endpoint: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        resp = httpx.post(endpoint, json=payload, timeout=20.0)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"MCP error: {body['error']}")
        return body

    def _tool_call(self, endpoint: str, name: str, arguments: dict[str, Any]) -> Any:
        raw = self._rpc_call(
            endpoint,
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        result = raw.get("result", {})
        if isinstance(result, dict) and "content" in result:
            content = result.get("content")
            if isinstance(content, list) and content:
                first = content[0]
                if isinstance(first, dict) and "text" in first:
                    try:
                        return json.loads(first["text"])
                    except Exception:
                        return first["text"]
        return result

    def _retrieve_graph_hits(self, endpoint: str, query: str) -> list[dict[str, Any]]:
        payload = self._tool_call(endpoint, "retrieve_context", {"query": query, "limit": self._cfg.graph_top_k})
        if isinstance(payload, list):
            return [p for p in payload if isinstance(p, dict)]
        return []

    def _build_graph_context(self, endpoint: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for hit in hits:
            qname = str(hit.get("qualified_name") or "")
            item = {
                "qualified_name": qname,
                "symbol_type": hit.get("symbol_type"),
                "file_path": hit.get("file_path"),
                "line_start": hit.get("line_start"),
                "line_end": hit.get("line_end"),
            }
            if self._cfg.include_relations and qname:
                try:
                    graph = self._tool_call(
                        endpoint,
                        "find_call_graph",
                        {"qualified_name": qname, "depth": self._cfg.relation_depth},
                    )
                    if isinstance(graph, dict):
                        item["callers"] = graph.get("callers", [])
                        item["callees"] = graph.get("callees", [])
                except Exception as exc:
                    item["relation_error"] = str(exc)
            items.append(item)
        return items

    def _build_fallback_snippets(self, query: str, graph_hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fallback: list[dict[str, Any]] = []

        for hit in graph_hits[: self._cfg.fallback_max_files]:
            file_path = str(hit.get("file_path") or "")
            if not file_path:
                continue
            snippet = read_code_snippet(
                self._cfg.repo_root,
                file_path,
                int(hit.get("line_start") or 1),
                int(hit.get("line_end") or 1),
                context_lines=self._cfg.fallback_context_lines,
            )
            if snippet:
                fallback.append(
                    {
                        "source": "symbol-snippet",
                        "file_path": file_path,
                        "line_start": int(hit.get("line_start") or 1),
                        "line_end": int(hit.get("line_end") or 1),
                        "snippet": snippet,
                    }
                )

        if fallback:
            return fallback

        # Last-resort fallback: keyword search in Python files only.
        needle = query.strip().lower()
        if not needle:
            return fallback

        scanned = 0
        for path in self._cfg.repo_root.rglob("*.py"):
            scanned += 1
            if scanned > 300:
                break
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            idx = text.lower().find(needle)
            if idx < 0:
                continue

            line_start = text[:idx].count("\n") + 1
            line_end = min(line_start + 20, line_start + text[idx:].count("\n"))
            rel = str(path.relative_to(self._cfg.repo_root)).replace("\\", "/")
            snippet = read_code_snippet(
                self._cfg.repo_root,
                rel,
                line_start,
                line_end,
                context_lines=self._cfg.fallback_context_lines,
            )
            if snippet:
                fallback.append(
                    {
                        "source": "keyword-fallback",
                        "file_path": rel,
                        "line_start": line_start,
                        "line_end": line_end,
                        "snippet": snippet,
                    }
                )
            if len(fallback) >= self._cfg.fallback_max_files:
                break

        return fallback
