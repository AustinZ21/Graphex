"""Unit tests for the Python AST parser."""

from __future__ import annotations

import textwrap
import tempfile
import os

import pytest

from backend.indexer.parser import PythonParser, discover_files, SUPPORTED_EXTENSIONS


@pytest.fixture()
def tmp_py(tmp_path):
    """Write a temporary Python file and return its path."""
    def _write(source: str) -> str:
        f = tmp_path / "sample.py"
        f.write_text(textwrap.dedent(source))
        return str(f)
    return _write


def test_parse_function(tmp_py):
    path = tmp_py("""\
        def greet(name: str) -> str:
            return f"Hello {name}"
    """)
    result = PythonParser().parse(path)
    assert result.parse_error is None
    names = [s.name for s in result.symbols]
    assert "greet" in names
    sym = next(s for s in result.symbols if s.name == "greet")
    assert sym.symbol_type == "function"
    assert sym.line_start == 1


def test_parse_async_function(tmp_py):
    path = tmp_py("""\
        async def fetch() -> None:
            pass
    """)
    result = PythonParser().parse(path)
    sym = next(s for s in result.symbols if s.name == "fetch")
    assert sym.symbol_type == "async_function"


def test_parse_class_and_method(tmp_py):
    path = tmp_py("""\
        class Indexer:
            def run(self) -> None:
                pass
            async def arun(self) -> None:
                pass
    """)
    result = PythonParser().parse(path)
    types = {s.name: s.symbol_type for s in result.symbols}
    assert types["Indexer"] == "class"
    assert types["run"] == "method"
    assert types["arun"] == "async_method"


def test_parse_imports(tmp_py):
    path = tmp_py("""\
        import os
        from pathlib import Path
    """)
    result = PythonParser().parse(path)
    modules = [i.imported_module for i in result.imports]
    assert "os" in modules
    assert "pathlib" in modules


def test_parse_syntax_error(tmp_py):
    path = tmp_py("def broken(:\n    pass\n")
    result = PythonParser().parse(path)
    assert result.parse_error is not None
    assert result.symbols == []


def test_discover_files(tmp_path):
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "b.txt").write_text("skip")
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "c.py").write_text("y = 2")
    skip = tmp_path / "__pycache__"
    skip.mkdir()
    (skip / "d.py").write_text("z = 3")

    found = list(discover_files(str(tmp_path)))
    paths = [os.path.basename(p) for p in found]
    assert "a.py" in paths
    assert "c.py" in paths
    assert "b.txt" not in paths
    assert "d.py" not in paths  # inside __pycache__
