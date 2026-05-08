"""Context quality benchmarking with Hallucination Pressure Score (HPS).

This module scores paired baseline-vs-CG context bundles before they are sent
to an LLM. HPS is a deterministic proxy for context-induced hallucination risk;
it does not score model answers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.perf.token_efficiency import estimate_tokens


class ContextQualityInputError(ValueError):
    """Raised when a context quality benchmark payload is invalid."""


DEFAULT_HPS_WEIGHTS = {
    "missingEvidence": 0.45,
    "noise": 0.35,
    "redundancy": 0.10,
    "ambiguity": 0.10,
}


@dataclass
class ContextModeScore:
    """Score for one context bundle mode, such as baseline or CG."""

    mode: str
    total_tokens: int
    useful_tokens: int
    useless_tokens: int
    duplicate_tokens: int
    covered_gold_items: list[str]
    missing_gold_items: list[str]
    gold_coverage: float
    context_precision: float
    context_recall: float
    noise_ratio: float
    redundancy_ratio: float
    ambiguous_symbol_hits: int
    total_symbol_hits: int
    ambiguity_ratio: float
    hallucination_pressure_score: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "totalTokens": self.total_tokens,
            "usefulTokens": self.useful_tokens,
            "uselessTokens": self.useless_tokens,
            "duplicateTokens": self.duplicate_tokens,
            "coveredGoldItems": self.covered_gold_items,
            "missingGoldItems": self.missing_gold_items,
            "goldCoverage": self.gold_coverage,
            "contextPrecision": self.context_precision,
            "contextRecall": self.context_recall,
            "noiseRatio": self.noise_ratio,
            "redundancyRatio": self.redundancy_ratio,
            "ambiguousSymbolHits": self.ambiguous_symbol_hits,
            "totalSymbolHits": self.total_symbol_hits,
            "ambiguityRatio": self.ambiguity_ratio,
            "hallucinationPressureScore": self.hallucination_pressure_score,
        }


def score_context_mode(
    *,
    mode: str,
    segment: dict[str, Any],
    gold_items: list[str],
    supporting_items: list[str],
    target_symbols: list[str],
    repo_root: Path,
    weights: dict[str, float] | None = None,
) -> ContextModeScore:
    """Score one context bundle for token waste, evidence coverage, and HPS."""
    if not isinstance(segment, dict):
        raise ContextQualityInputError(f"{mode} must be an object")

    active_weights = _normalize_weights(weights or DEFAULT_HPS_WEIGHTS)
    gold_set = set(_string_list(gold_items, "goldItems"))
    useful_evidence = gold_set | set(_string_list(supporting_items, "supportingItems"))
    chunks = _resolve_chunks(segment, repo_root=repo_root, mode=mode)

    total_tokens = 0
    useful_tokens = 0
    duplicate_tokens = 0
    covered_gold: set[str] = set()
    seen_chunk_hashes: set[str] = set()
    symbols: list[str] = _string_list(segment.get("symbols") or [], f"{mode}.symbols")

    for chunk in chunks:
        text = chunk["text"]
        chunk_tokens = estimate_tokens(text)
        total_tokens += chunk_tokens

        evidence = set(_string_list(chunk.get("evidence") or [], f"{mode}.chunks.evidence"))
        covered_gold.update(evidence & gold_set)
        if evidence & useful_evidence or bool(chunk.get("useful")):
            useful_tokens += chunk_tokens

        chunk_symbols = _string_list(chunk.get("symbols") or [], f"{mode}.chunks.symbols")
        symbols.extend(chunk_symbols)

        normalized = _normalize_text(text)
        if normalized:
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if digest in seen_chunk_hashes:
                duplicate_tokens += chunk_tokens
            else:
                seen_chunk_hashes.add(digest)

    useful_tokens = min(useful_tokens, total_tokens)
    useless_tokens = max(0, total_tokens - useful_tokens)
    missing_gold = sorted(gold_set - covered_gold)
    covered_gold_items = sorted(covered_gold)

    gold_coverage = _ratio(len(covered_gold), len(gold_set))
    context_precision = _ratio(useful_tokens, total_tokens)
    context_recall = gold_coverage
    noise_ratio = _ratio(useless_tokens, total_tokens)
    redundancy_ratio = _ratio(duplicate_tokens, total_tokens)
    ambiguous_symbol_hits, total_symbol_hits = _count_ambiguous_symbols(symbols, target_symbols)
    ambiguity_ratio = _ratio(ambiguous_symbol_hits, total_symbol_hits)

    hps = 100.0 * (
        active_weights["missingEvidence"] * (1.0 - gold_coverage)
        + active_weights["noise"] * noise_ratio
        + active_weights["redundancy"] * redundancy_ratio
        + active_weights["ambiguity"] * ambiguity_ratio
    )

    return ContextModeScore(
        mode=mode,
        total_tokens=total_tokens,
        useful_tokens=useful_tokens,
        useless_tokens=useless_tokens,
        duplicate_tokens=duplicate_tokens,
        covered_gold_items=covered_gold_items,
        missing_gold_items=missing_gold,
        gold_coverage=round(gold_coverage, 4),
        context_precision=round(context_precision, 4),
        context_recall=round(context_recall, 4),
        noise_ratio=round(noise_ratio, 4),
        redundancy_ratio=round(redundancy_ratio, 4),
        ambiguous_symbol_hits=ambiguous_symbol_hits,
        total_symbol_hits=total_symbol_hits,
        ambiguity_ratio=round(ambiguity_ratio, 4),
        hallucination_pressure_score=round(hps, 2),
    )


def benchmark_context_quality(payload: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    """Benchmark baseline-vs-CG context quality across one or more cases."""
    if not isinstance(payload, dict):
        raise ContextQualityInputError("request body must be a JSON object")

    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ContextQualityInputError("request body must include a non-empty cases array")

    weights = _normalize_weights(payload.get("weights") or DEFAULT_HPS_WEIGHTS)
    reports = [_score_case(case, repo_root=repo_root, weights=weights) for case in cases]

    return {
        "ok": True,
        "metric": "hallucination-pressure-score",
        "method": "hps-context-quality-v1",
        "weights": weights,
        "cases": reports,
        "summary": _summarize(reports),
    }


def _score_case(case: Any, *, repo_root: Path, weights: dict[str, float]) -> dict[str, Any]:
    if not isinstance(case, dict):
        raise ContextQualityInputError("each case must be an object")

    case_id = str(case.get("id") or "")
    if not case_id:
        raise ContextQualityInputError("each case must include id")

    gold_items = _string_list(case.get("goldItems") or case.get("gold_items") or [], f"{case_id}.goldItems")
    if not gold_items:
        raise ContextQualityInputError(f"case {case_id} must include goldItems")

    supporting_items = _string_list(
        case.get("supportingItems") or case.get("supporting_items") or [],
        f"{case_id}.supportingItems",
    )
    target_symbols = _string_list(
        case.get("targetSymbols") or case.get("target_symbols") or [],
        f"{case_id}.targetSymbols",
    )

    baseline = score_context_mode(
        mode="baseline",
        segment=case.get("baseline"),
        gold_items=gold_items,
        supporting_items=supporting_items,
        target_symbols=target_symbols,
        repo_root=repo_root,
        weights=weights,
    )
    cg = score_context_mode(
        mode="cg",
        segment=case.get("cg"),
        gold_items=gold_items,
        supporting_items=supporting_items,
        target_symbols=target_symbols,
        repo_root=repo_root,
        weights=weights,
    )

    return {
        "id": case_id,
        "project": str(case.get("project") or ""),
        "category": str(case.get("category") or ""),
        "query": str(case.get("query") or ""),
        "goldItems": gold_items,
        "targetSymbols": target_symbols,
        "baseline": baseline.as_dict(),
        "cg": cg.as_dict(),
        "comparison": _compare_scores(baseline, cg),
    }


def _compare_scores(baseline: ContextModeScore, cg: ContextModeScore) -> dict[str, Any]:
    return {
        "tokenReductionPercent": _percent_reduction(baseline.total_tokens, cg.total_tokens),
        "uselessTokenReductionPercent": _percent_reduction(baseline.useless_tokens, cg.useless_tokens),
        "hpsReductionPercent": _percent_reduction(
            baseline.hallucination_pressure_score,
            cg.hallucination_pressure_score,
        ),
        "goldCoverageDelta": round(cg.gold_coverage - baseline.gold_coverage, 4),
        "precisionDelta": round(cg.context_precision - baseline.context_precision, 4),
    }


def _summarize(reports: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(reports)
    baseline_hps = [item["baseline"]["hallucinationPressureScore"] for item in reports]
    cg_hps = [item["cg"]["hallucinationPressureScore"] for item in reports]
    baseline_tokens = [item["baseline"]["totalTokens"] for item in reports]
    cg_tokens = [item["cg"]["totalTokens"] for item in reports]
    hps_reductions = [item["comparison"]["hpsReductionPercent"] for item in reports]
    token_reductions = [item["comparison"]["tokenReductionPercent"] for item in reports]

    return {
        "caseCount": count,
        "avgBaselineHps": _average(baseline_hps),
        "avgCgHps": _average(cg_hps),
        "avgHpsReductionPercent": _average(hps_reductions),
        "avgBaselineTokens": _average(baseline_tokens),
        "avgCgTokens": _average(cg_tokens),
        "avgTokenReductionPercent": _average(token_reductions),
    }


def _resolve_chunks(segment: dict[str, Any], *, repo_root: Path, mode: str) -> list[dict[str, Any]]:
    raw_chunks = segment.get("chunks")
    chunks: list[dict[str, Any]] = []

    if raw_chunks is not None:
        if not isinstance(raw_chunks, list):
            raise ContextQualityInputError(f"{mode}.chunks must be an array")
        for index, item in enumerate(raw_chunks):
            if isinstance(item, str):
                chunks.append({"id": f"chunk-{index + 1}", "text": item, "evidence": []})
                continue
            if not isinstance(item, dict):
                raise ContextQualityInputError(f"{mode}.chunks entries must be objects or strings")
            chunk = dict(item)
            text = str(chunk.get("text") or "")
            file_path = chunk.get("filePath") or chunk.get("file_path")
            if not text and file_path:
                text = _read_repo_file(str(file_path), repo_root=repo_root, mode=mode)
            chunk["text"] = text
            chunks.append(chunk)
        return chunks

    if segment.get("text"):
        chunks.append({"id": f"{mode}-text", "text": str(segment.get("text")), "evidence": []})

    snippets = segment.get("snippets") or []
    if snippets:
        if not isinstance(snippets, list):
            raise ContextQualityInputError(f"{mode}.snippets must be an array")
        for index, snippet in enumerate(snippets):
            chunks.append({"id": f"{mode}-snippet-{index + 1}", "text": str(snippet), "evidence": []})

    for index, file_path in enumerate(_string_list(segment.get("filePaths") or [], f"{mode}.filePaths")):
        chunks.append(
            {
                "id": f"{mode}-file-{index + 1}",
                "text": _read_repo_file(file_path, repo_root=repo_root, mode=mode),
                "evidence": [],
            }
        )

    return chunks


def _read_repo_file(file_path: str, *, repo_root: Path, mode: str) -> str:
    candidate = Path(file_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ContextQualityInputError(f"{mode} filePath is outside repo: {file_path}") from exc
    if not resolved.exists() or not resolved.is_file():
        raise ContextQualityInputError(f"{mode} filePath does not exist: {file_path}")
    return resolved.read_text(encoding="utf-8", errors="replace")


def _count_ambiguous_symbols(symbols: list[str], target_symbols: list[str]) -> tuple[int, int]:
    if not symbols or not target_symbols:
        return 0, 0

    target_exact = set(target_symbols)
    target_simple = {_simple_symbol_name(symbol) for symbol in target_symbols}
    matching_hits = [symbol for symbol in symbols if _simple_symbol_name(symbol) in target_simple]
    ambiguous = [symbol for symbol in matching_hits if symbol not in target_exact]
    return len(ambiguous), len(matching_hits)


def _simple_symbol_name(symbol: str) -> str:
    value = symbol.replace("::", ".")
    if ":" in value:
        value = value.rsplit(":", 1)[-1]
    if "." in value:
        value = value.rsplit(".", 1)[-1]
    return value


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ContextQualityInputError(f"{field} must be an array")
    return [str(item) for item in value if item is not None and str(item)]


def _normalize_weights(weights: dict[str, Any]) -> dict[str, float]:
    if not isinstance(weights, dict):
        raise ContextQualityInputError("weights must be an object")
    normalized = dict(DEFAULT_HPS_WEIGHTS)
    for key in normalized:
        if key in weights:
            normalized[key] = float(weights[key])
    total = sum(normalized.values())
    if total <= 0:
        raise ContextQualityInputError("weights must sum to a positive value")
    return {key: round(value / total, 4) for key, value in normalized.items()}


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def _percent_reduction(before: float, after: float) -> float:
    if before <= 0:
        return 0.0
    return round(((before - after) / before) * 100.0, 2)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)