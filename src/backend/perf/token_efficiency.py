"""Token efficiency benchmark helpers for ContextGraph-side reuse.

This module compares token estimates between:
- baseline context (traditional broad context)
- CG/MCP-reduced context (targeted retrieval)

The estimator is heuristic by design and intended for trend analysis, not billing-grade accounting.
"""

from __future__ import annotations

from pathlib import Path


class TokenBenchmarkInputError(ValueError):
    """Raised when benchmark request payload is invalid."""


def estimate_tokens(text: str) -> int:
    """Estimate tokens from text with a mixed-language heuristic.

    Rules:
    - Non-CJK chars: ~4 chars/token
    - CJK chars: ~1.6 chars/token
    """
    if not text:
        return 0

    total_chars = len(text)
    cjk_chars = 0
    for ch in text:
        code = ord(ch)
        if (
            0x3400 <= code <= 0x4DBF
            or 0x4E00 <= code <= 0x9FFF
            or 0x3040 <= code <= 0x30FF
            or 0xAC00 <= code <= 0xD7AF
        ):
            cjk_chars += 1

    other_chars = max(0, total_chars - cjk_chars)
    estimate = int((other_chars / 4.0) + (cjk_chars / 1.6) + 0.999999)
    return max(0, estimate)


def _resolve_segment(segment: dict | str | None, repo_root: Path, segment_name: str) -> tuple[str, dict]:
    diag = {
        "segment": segment_name,
        "sourceType": "empty",
        "chars": 0,
        "fileCount": 0,
        "filesRead": [],
        "missingFiles": [],
    }

    if segment is None:
        return "", diag

    if isinstance(segment, str):
        diag["sourceType"] = "rawString"
        diag["chars"] = len(segment)
        return segment, diag

    if not isinstance(segment, dict):
        raise TokenBenchmarkInputError(f"{segment_name} must be an object, string, or null")

    chunks: list[str] = []

    text = segment.get("text")
    if text:
        chunks.append(str(text))
        diag["sourceType"] = "text"

    snippets = segment.get("snippets")
    if snippets:
        if not isinstance(snippets, list):
            raise TokenBenchmarkInputError(f"{segment_name}.snippets must be an array")
        for item in snippets:
            if item is None:
                continue
            chunks.append(str(item))
        if diag["sourceType"] == "empty":
            diag["sourceType"] = "snippets"

    file_paths = segment.get("filePaths")
    if file_paths:
        if not isinstance(file_paths, list):
            raise TokenBenchmarkInputError(f"{segment_name}.filePaths must be an array")

        for file_path in file_paths:
            if not file_path:
                continue
            raw_path = str(file_path)
            candidate = Path(raw_path)
            resolved = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()

            try:
                resolved.relative_to(repo_root)
            except ValueError:
                diag["missingFiles"].append(f"outside-repo:{raw_path}")
                continue

            if not resolved.exists() or not resolved.is_file():
                diag["missingFiles"].append(raw_path)
                continue

            chunks.append(resolved.read_text(encoding="utf-8", errors="replace"))
            diag["filesRead"].append(str(resolved.relative_to(repo_root)).replace("\\", "/"))

        if diag["sourceType"] == "empty":
            diag["sourceType"] = "filePaths"

    content = "\n".join(chunks)
    diag["chars"] = len(content)
    diag["fileCount"] = len(diag["filesRead"])
    return content, diag


def benchmark_token_efficiency(payload: dict, repo_root: Path) -> dict:
    """Benchmark token efficiency between baseline and CG/MCP contexts."""
    if not isinstance(payload, dict):
        raise TokenBenchmarkInputError("request body must be a JSON object")

    baseline = payload.get("baseline")
    cg = payload.get("cg")
    if baseline is None or cg is None:
        raise TokenBenchmarkInputError("request body must include both baseline and cg")

    baseline_text, baseline_diag = _resolve_segment(baseline, repo_root=repo_root, segment_name="baseline")
    cg_text, cg_diag = _resolve_segment(cg, repo_root=repo_root, segment_name="cg")

    baseline_tokens = estimate_tokens(baseline_text)
    cg_tokens = estimate_tokens(cg_text)
    saved_tokens = baseline_tokens - cg_tokens
    saved_percent = round((saved_tokens / baseline_tokens) * 100, 2) if baseline_tokens > 0 else 0.0
    ratio = round(baseline_tokens / cg_tokens, 3) if cg_tokens > 0 else None

    return {
        "ok": True,
        "metric": "cg-token-savings",
        "method": "heuristic-char-mix-v1",
        "query": str(payload.get("query", "")),
        "notes": str(payload.get("notes", "")),
        "baselineTokens": baseline_tokens,
        "cgTokens": cg_tokens,
        "savedTokens": saved_tokens,
        "savedPercent": saved_percent,
        "baselineToCgRatio": ratio,
        "baseline": baseline_diag,
        "cg": cg_diag,
    }
