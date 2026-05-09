"""API endpoints for the large-scale ContextGraph viewer."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth.dependencies import get_registry, require_admin

KNOWN_EDGE_TYPES = ("CONTAINS", "DEFINES", "IMPORTS", "CALLS", "USES_VARIABLE", "FLOWS_TO")
KNOWN_NODE_LABELS = ("Repository", "File", "Symbol", "Variable")
DEFAULT_CHUNK_LIMIT = 50_000
MAX_CHUNK_LIMIT = 100_000
_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

router = APIRouter(prefix="/viewer", tags=["viewer"])


def _normalize_project_name(project_name: str) -> str:
    normalized = project_name.strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="Project name is required")
    if not _PROJECT_NAME_RE.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail="Project name may only contain letters, numbers, dot, dash, and underscore",
        )
    return normalized


def _coerce_count(row: list[Any] | tuple[Any, ...] | None) -> int:
    if not row:
        return 0
    try:
        return max(0, int(row[0] or 0))
    except (TypeError, ValueError):
        return 0


def _query_count(graph: Any, cypher: str) -> int:
    result = graph.query(cypher)
    rows = getattr(result, "result_set", None) or []
    return _coerce_count(rows[0] if rows else None)


def _primary_label(labels: Any) -> str:
    if isinstance(labels, list) and labels:
        return str(labels[0])
    if isinstance(labels, tuple) and labels:
        return str(labels[0])
    if isinstance(labels, str) and labels:
        return labels
    return "Node"


def _node_identity(
    internal_id: Any,
    labels: Any,
    qualified_name: Any,
    path: Any,
    name: Any,
) -> str:
    label = _primary_label(labels)
    stable = qualified_name or path or name or internal_id
    return f"{label}:{stable}"


def _node_payload(row: list[Any], offset: int) -> dict[str, Any]:
    internal_id = row[offset]
    labels = row[offset + 1]
    qualified_name = row[offset + 2]
    path = row[offset + 3]
    name = row[offset + 4]
    symbol_type = row[offset + 5]
    language = row[offset + 6]
    file_path = row[offset + 7]
    line_start = row[offset + 8]
    kind = _primary_label(labels)
    label = str(name or qualified_name or path or internal_id)
    subtitle = str(symbol_type or language or file_path or "")
    return {
        "id": _node_identity(internal_id, labels, qualified_name, path, name),
        "label": label,
        "kind": kind,
        "subtitle": subtitle,
        "file_path": file_path or path,
        "line_start": line_start,
    }


def _chunk_from_rows(project_name: str, rows: list[list[Any]], offset: int, limit: int) -> dict[str, Any]:
    points_by_id: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []

    for row in rows:
        rel_id = row[0]
        rel_type = str(row[1])
        source = _node_payload(row, 2)
        target = _node_payload(row, 11)
        points_by_id.setdefault(source["id"], source)
        points_by_id.setdefault(target["id"], target)
        links.append(
            {
                "id": f"{rel_type}:{rel_id}",
                "source": source["id"],
                "target": target["id"],
                "type": rel_type,
            }
        )

    return {
        "project_name": project_name,
        "offset": offset,
        "limit": limit,
        "next_offset": offset + len(links) if len(links) == limit else None,
        "points": list(points_by_id.values()),
        "links": links,
    }


def _parse_edge_types(edge_types: str | None) -> list[str]:
    if not edge_types:
        return list(KNOWN_EDGE_TYPES)
    requested = [part.strip().upper() for part in edge_types.split(",") if part.strip()]
    invalid = sorted(set(requested) - set(KNOWN_EDGE_TYPES))
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unsupported edge type(s): {', '.join(invalid)}")
    return requested or list(KNOWN_EDGE_TYPES)


@router.get("/graphs/{project_name}/stats")
async def graph_stats(
    project_name: str,
    _: dict = Depends(require_admin),
    registry=Depends(get_registry),
) -> dict[str, Any]:
    normalized_project = _normalize_project_name(project_name)
    if registry is None:
        raise HTTPException(status_code=503, detail="Graph registry is not available")

    graph = registry.get(normalized_project)
    node_counts = {label: _query_count(graph, f"MATCH (n:{label}) RETURN count(n)") for label in KNOWN_NODE_LABELS}
    edge_counts = {edge_type: _query_count(graph, f"MATCH ()-[r:{edge_type}]->() RETURN count(r)") for edge_type in KNOWN_EDGE_TYPES}

    return {
        "project_name": normalized_project,
        "node_counts": node_counts,
        "edge_counts": edge_counts,
        "total_nodes": sum(node_counts.values()),
        "total_edges": sum(edge_counts.values()),
        "default_chunk_limit": DEFAULT_CHUNK_LIMIT,
        "max_chunk_limit": MAX_CHUNK_LIMIT,
    }


@router.get("/graphs/{project_name}/chunk")
async def graph_chunk(
    project_name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_CHUNK_LIMIT, ge=1, le=MAX_CHUNK_LIMIT),
    edge_types: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=160),
    _: dict = Depends(require_admin),
    registry=Depends(get_registry),
) -> dict[str, Any]:
    normalized_project = _normalize_project_name(project_name)
    if registry is None:
        raise HTTPException(status_code=503, detail="Graph registry is not available")

    selected_edge_types = _parse_edge_types(edge_types)
    normalized_search = (search or "").strip().lower()
    search_clause = ""
    if normalized_search:
        search_clause = """
AND (
  toLower(coalesce(source.qualified_name, '')) CONTAINS $search OR
  toLower(coalesce(source.path, '')) CONTAINS $search OR
  toLower(coalesce(source.name, '')) CONTAINS $search OR
  toLower(coalesce(target.qualified_name, '')) CONTAINS $search OR
  toLower(coalesce(target.path, '')) CONTAINS $search OR
  toLower(coalesce(target.name, '')) CONTAINS $search
)
"""

    query = f"""
MATCH (source)-[rel]->(target)
WHERE type(rel) IN $edge_types
{search_clause}
WITH source, rel, target
ORDER BY id(rel)
SKIP $offset
LIMIT $limit
RETURN
  id(rel), type(rel),
  id(source), labels(source), source.qualified_name, source.path, source.name, source.symbol_type, source.language, source.file_path, source.line_start,
  id(target), labels(target), target.qualified_name, target.path, target.name, target.symbol_type, target.language, target.file_path, target.line_start
"""
    graph = registry.get(normalized_project)
    params = {
        "edge_types": selected_edge_types,
        "offset": offset,
        "limit": limit,
        "search": normalized_search,
    }
    result = graph.query(query, params)
    rows = getattr(result, "result_set", None) or []
    return _chunk_from_rows(normalized_project, rows, offset, limit)