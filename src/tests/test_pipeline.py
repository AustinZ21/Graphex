"""Pipeline-level tests for variable flow graph writes."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.graph import schema as S
from backend.indexer.call_analyzer import RawCall
from backend.indexer.parser import ParsedFile, ParsedVariable, ParsedVariableFlow
from backend.indexer.pipeline import IndexPipeline


def test_write_variable_flow_edges_writes_variable_nodes_and_local_flows() -> None:
    graph = MagicMock()
    pipeline = IndexPipeline(graph)
    parsed = ParsedFile(path="repo/service.py", language="python")
    parsed.variables.extend(
        [
            ParsedVariable("input", "pkg.render:input", "pkg.render", "repo/service.py", 10, "parameter"),
            ParsedVariable("label", "pkg.render:label", "pkg.render", "repo/service.py", 11, "local"),
        ]
    )
    parsed.variable_flows.append(
        ParsedVariableFlow("pkg.render:input", "pkg.render:label", "pkg.render", 11, "assignment")
    )

    stats = pipeline._write_variable_flow_edges(parsed)

    assert stats["variables"] == 2
    assert stats["variable_flows"] == 1
    calls = graph.query.call_args_list
    assert any(call.args[0] == S.EDGE_SYMBOL_HAS_VARIABLE for call in calls)
    assert any(call.kwargs == {} and call.args[1].get("flow_type") == "assignment" for call in calls if len(call.args) > 1)


def test_write_cross_scope_variable_flows_writes_argument_and_return_edges() -> None:
    graph = MagicMock()

    def side_effect(cypher: str, params: dict | None = None):
        result = MagicMock()
        if "role: 'parameter'" in cypher:
            result.result_set = [["pkg.callee:param"]]
        else:
            result.result_set = []
        return result

    graph.query.side_effect = side_effect
    pipeline = IndexPipeline(graph)
    raw_calls = [
        RawCall(
            caller_qname="pkg.caller",
            callee_name="callee",
            arg_names=["input"],
            result_var_name="result",
        )
    ]

    written = pipeline._write_cross_scope_variable_flows(raw_calls, {"callee": "pkg.callee"})

    assert written == 2
    flow_calls = [call for call in graph.query.call_args_list if len(call.args) > 1 and isinstance(call.args[1], dict) and call.args[1].get("flow_type") in {"argument", "call_return"}]
    assert any(call.args[1]["source_qname"] == "pkg.caller:input" and call.args[1]["target_qname"] == "pkg.callee:param" for call in flow_calls)
    assert any(call.args[1]["source_qname"] == "pkg.callee:__return__" and call.args[1]["target_qname"] == "pkg.caller:result" for call in flow_calls)