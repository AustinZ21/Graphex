"""Tests for FalkorDB GraphClient index creation behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.graph.client import GraphClient


def test_ensure_indexes_creates_variable_indexes() -> None:
    client = GraphClient()
    client.query = MagicMock()

    client.ensure_indexes()

    statements = [call.args[0] for call in client.query.call_args_list]
    assert "CREATE INDEX FOR (n:Variable) ON (n.name)" in statements
    assert "CREATE INDEX FOR (n:Variable) ON (n.qualified_name)" in statements
    assert "CREATE INDEX FOR (n:Variable) ON (n.scope_qname)" in statements


def test_ensure_indexes_ignores_existing_index_errors() -> None:
    client = GraphClient()

    def side_effect(cypher: str, params=None):
        if "Variable" in cypher:
            raise RuntimeError("index already exists")
        return MagicMock()

    client.query = MagicMock(side_effect=side_effect)

    client.ensure_indexes()

    assert client.query.call_count >= 1