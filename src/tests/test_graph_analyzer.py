"""Tests for call-graph analysis and metrics."""

from __future__ import annotations

import pytest

from backend.graph.analyzer import (
    CallGraphAnalyzer,
    CycleInfo,
    SymbolMetrics,
    GraphMetrics,
)


def test_build_call_graph():
    """Test building call graph from edges."""
    calls = [
        ("main", "foo"),
        ("main", "bar"),
        ("foo", "baz"),
        ("bar", "baz"),
    ]
    analyzer = CallGraphAnalyzer()
    analyzer.build_from_calls(calls)
    
    assert len(analyzer._all_symbols) == 4
    assert "baz" in analyzer._graph["foo"]
    assert "foo" in analyzer._reverse_graph["baz"]


def test_detect_cycles():
    """Test cycle detection."""
    calls = [
        ("a", "b"),
        ("b", "c"),
        ("c", "a"),  # cycle: a -> b -> c -> a
        ("c", "d"),
    ]
    analyzer = CallGraphAnalyzer()
    analyzer.build_from_calls(calls)
    cycles = analyzer.detect_cycles()
    
    assert len(cycles) > 0
    assert any(len(c.symbols) == 3 for c in cycles)


def test_no_cycles():
    """Test that acyclic graph has no cycles."""
    calls = [
        ("main", "foo"),
        ("foo", "bar"),
        ("bar", "baz"),
    ]
    analyzer = CallGraphAnalyzer()
    analyzer.build_from_calls(calls)
    cycles = analyzer.detect_cycles()
    
    assert len(cycles) == 0


def test_compute_fan_in():
    """Test fan-in computation."""
    calls = [
        ("main", "util"),
        ("foo", "util"),
        ("bar", "util"),
    ]
    analyzer = CallGraphAnalyzer()
    analyzer.build_from_calls(calls)
    fan_in = analyzer.compute_fan_in()
    
    assert fan_in["util"] == 3
    assert fan_in["main"] == 0
    assert fan_in["foo"] == 0
    assert fan_in["bar"] == 0


def test_compute_fan_out():
    """Test fan-out computation."""
    calls = [
        ("orchestrator", "util"),
        ("orchestrator", "db"),
        ("orchestrator", "cache"),
        ("util", "helper"),
    ]
    analyzer = CallGraphAnalyzer()
    analyzer.build_from_calls(calls)
    fan_out = analyzer.compute_fan_out()
    
    assert fan_out["orchestrator"] == 3
    assert fan_out["util"] == 1
    assert fan_out["db"] == 0
    assert fan_out["cache"] == 0


def test_compute_call_depth():
    """Test call depth computation (from roots)."""
    calls = [
        ("root", "level1a"),
        ("root", "level1b"),
        ("level1a", "level2"),
        ("level1b", "level2"),
        ("level2", "leaf"),
    ]
    analyzer = CallGraphAnalyzer()
    analyzer.build_from_calls(calls)
    depths = analyzer.compute_call_depth()
    
    assert depths["root"] == 0
    assert depths["level1a"] == 1
    assert depths["level1b"] == 1
    assert depths["level2"] == 2
    assert depths["leaf"] == 3


def test_find_critical_functions():
    """Test finding critical (central) functions."""
    calls = [
        ("main", "hub"),
        ("a", "hub"),
        ("b", "hub"),
        ("c", "hub"),
        ("hub", "util1"),
        ("hub", "util2"),
        ("util1", "core"),
        ("util2", "core"),
    ]
    analyzer = CallGraphAnalyzer()
    analyzer.build_from_calls(calls)
    critical = analyzer.find_critical_functions(top_n=3)
    
    # hub should be high-ranked (high fan-in, moderate fan-out)
    critical_names = [name for name, _ in critical]
    assert "hub" in critical_names


def test_compute_metrics():
    """Test overall graph metrics computation."""
    calls = [
        ("a", "b"),
        ("b", "c"),
        ("c", "a"),
        ("d", "e"),
        ("e", "f"),
    ]
    analyzer = CallGraphAnalyzer()
    analyzer.build_from_calls(calls)
    metrics = analyzer.compute_metrics()
    
    assert metrics.total_symbols == 6
    assert metrics.total_calls == 5
    assert metrics.total_cycles > 0
    assert metrics.symbols_with_cycles > 0
    assert metrics.avg_fan_in >= 0
    assert metrics.max_fan_in > 0
    assert metrics.max_call_depth > 0


def test_cycle_info_str():
    """Test cycle string representation."""
    cycle = CycleInfo(symbols=["a", "b", "c"], length=3)
    expected = "a -> b -> c -> a"
    assert str(cycle) == expected
