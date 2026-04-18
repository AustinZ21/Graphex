"""Tests for call graph extractor (call_analyzer.py)."""

import ast

from backend.indexer.call_analyzer import CallAnalyzer


def _analyze(source: str, module: str = "mymod") -> list:
    tree = ast.parse(source)
    return CallAnalyzer().extract(tree, "mymod.py", module)


def test_simple_function_call():
    src = """
def a():
    b()
"""
    calls = _analyze(src)
    assert any(c.caller_qname.endswith(".a") and c.callee_name == "b" for c in calls)


def test_method_call_attribute():
    src = """
class Foo:
    def run(self):
        self.helper()
"""
    calls = _analyze(src)
    assert any(c.callee_name == "helper" for c in calls)


def test_async_function_call():
    src = """
async def producer():
    await do_work()
"""
    calls = _analyze(src)
    assert any(c.callee_name == "do_work" for c in calls)


def test_no_calls_returns_empty():
    src = """
def noop():
    x = 1 + 2
"""
    calls = _analyze(src)
    assert calls == []


def test_nested_class_method():
    src = """
class Indexer:
    def index(self):
        parse(path)
        self.write(data)
"""
    calls = _analyze(src)
    callee_names = {c.callee_name for c in calls}
    assert "parse" in callee_names
    assert "write" in callee_names
