from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.auth.dependencies import get_registry, require_admin
from backend.main import app


class _FakeRegistry:
    def __init__(self, graph: MagicMock) -> None:
        self.graph = graph
        self.requested_projects: list[str] = []

    def get(self, project_name: str) -> MagicMock:
        self.requested_projects.append(project_name)
        return self.graph


def _result(rows: list[list]) -> MagicMock:
    result = MagicMock()
    result.result_set = rows
    return result


def test_viewer_stats_returns_known_node_and_edge_counts() -> None:
    graph = MagicMock()
    graph.query.side_effect = [
        _result([[2]]),
        _result([[3]]),
        _result([[5]]),
        _result([[0]]),
        _result([[7]]),
        _result([[11]]),
        _result([[13]]),
        _result([[17]]),
        _result([[19]]),
        _result([[23]]),
    ]
    registry = _FakeRegistry(graph)

    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_registry] = lambda: registry
    try:
        response = TestClient(app).get("/api/viewer/graphs/ContextGraph/stats")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "project_name": "contextgraph",
        "node_counts": {
            "Repository": 2,
            "File": 3,
            "Symbol": 5,
            "Variable": 0,
        },
        "edge_counts": {
            "CONTAINS": 7,
            "DEFINES": 11,
            "IMPORTS": 13,
            "CALLS": 17,
            "USES_VARIABLE": 19,
            "FLOWS_TO": 23,
        },
        "total_nodes": 10,
        "total_edges": 90,
        "default_chunk_limit": 50000,
        "max_chunk_limit": 100000,
    }
    assert registry.requested_projects == ["contextgraph"]


def test_viewer_chunk_deduplicates_points_and_returns_next_offset() -> None:
    graph = MagicMock()
    graph.query.return_value = _result(
        [
            [
                7,
                "CALLS",
                1,
                ["Symbol"],
                "pkg.source",
                None,
                "source",
                "function",
                None,
                "src/source.py",
                10,
                2,
                ["Symbol"],
                "pkg.target",
                None,
                "target",
                "function",
                None,
                "src/target.py",
                20,
            ],
            [
                8,
                "CALLS",
                1,
                ["Symbol"],
                "pkg.source",
                None,
                "source",
                "function",
                None,
                "src/source.py",
                10,
                3,
                ["File"],
                None,
                "src/third.py",
                None,
                None,
                "python",
                "src/third.py",
                None,
            ],
        ]
    )
    registry = _FakeRegistry(graph)

    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_registry] = lambda: registry
    try:
        response = TestClient(app).get("/api/viewer/graphs/contextgraph/chunk?offset=40&limit=2")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["project_name"] == "contextgraph"
    assert body["offset"] == 40
    assert body["limit"] == 2
    assert body["next_offset"] == 42
    assert body["links"] == [
        {"id": "CALLS:7", "source": "Symbol:pkg.source", "target": "Symbol:pkg.target", "type": "CALLS"},
        {"id": "CALLS:8", "source": "Symbol:pkg.source", "target": "File:src/third.py", "type": "CALLS"},
    ]
    assert body["points"] == [
        {
            "id": "Symbol:pkg.source",
            "label": "source",
            "kind": "Symbol",
            "subtitle": "function",
            "file_path": "src/source.py",
            "line_start": 10,
        },
        {
            "id": "Symbol:pkg.target",
            "label": "target",
            "kind": "Symbol",
            "subtitle": "function",
            "file_path": "src/target.py",
            "line_start": 20,
        },
        {
            "id": "File:src/third.py",
            "label": "src/third.py",
            "kind": "File",
            "subtitle": "python",
            "file_path": "src/third.py",
            "line_start": None,
        },
    ]


def test_viewer_rejects_invalid_project_name() -> None:
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    try:
        response = TestClient(app).get("/api/viewer/graphs/bad%20name/stats")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "Project name may only contain letters, numbers, dot, dash, and underscore"


def test_viewer_entrypoint_is_served() -> None:
    response = TestClient(app).get("/viewer/")

    assert response.status_code == 200
    assert "<title>Viewer</title>" in response.text


def test_viewer_entrypoint_redirects_to_trailing_slash() -> None:
    response = TestClient(app).get("/viewer", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/viewer/"