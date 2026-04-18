"""Unit tests for the Python and TS/JS parsers."""

from __future__ import annotations

import textwrap
import tempfile
import os

import pytest

from backend.indexer.parser import (
    PythonParser,
    SourceParser,
    TypeScriptJavaScriptParser,
    discover_files,
    SUPPORTED_EXTENSIONS,
)


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
    (tmp_path / "a.ts").write_text("export function x() {}")
    (tmp_path / "b.txt").write_text("skip")
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "c.py").write_text("y = 2")
    (sub / "d.jsx").write_text("export const View = () => <div />")
    skip = tmp_path / "__pycache__"
    skip.mkdir()
    (skip / "e.py").write_text("z = 3")

    found = list(discover_files(str(tmp_path)))
    paths = [os.path.basename(p) for p in found]
    assert "a.py" in paths
    assert "a.ts" in paths
    assert "c.py" in paths
    assert "d.jsx" in paths
    assert "b.txt" not in paths
    assert "e.py" not in paths  # inside __pycache__


def test_parse_typescript_symbols_and_imports(tmp_path):
    path = tmp_path / "sample.ts"
    path.write_text(
        textwrap.dedent(
            """\
            import { foo } from './lib';
            export interface User { id: string }
            export type UserId = string;
            export enum Status { Active = 'active' }
            export class Service {
                run() {
                    return foo();
                }
            }
            export function buildUser() {
                return new Service();
            }
            export const loadUser = async () => {
                return buildUser();
            };
            """
        ),
        encoding="utf-8",
    )

    result = TypeScriptJavaScriptParser().parse(str(path))
    names = {s.name: s.symbol_type for s in result.symbols}
    assert result.language == "typescript"
    assert names["User"] == "interface"
    assert names["UserId"] == "type"
    assert names["Status"] == "enum"
    assert names["Service"] == "class"
    assert names["run"] == "method"
    assert names["buildUser"] == "function"
    assert names["loadUser"] == "function"
    assert "./lib" in [i.imported_module for i in result.imports]


def test_parse_javascript_symbols_and_requires(tmp_path):
    path = tmp_path / "sample.js"
    path.write_text(
        textwrap.dedent(
            """\
            const pathUtil = require('path');
            class Worker {
                start() {
                    return true;
                }
            }
            function boot() {
                return new Worker();
            }
            const render = () => boot();
            """
        ),
        encoding="utf-8",
    )

    result = TypeScriptJavaScriptParser().parse(str(path))
    names = {s.name: s.symbol_type for s in result.symbols}
    assert result.language == "javascript"
    assert names["Worker"] == "class"
    assert names["start"] == "method"
    assert names["boot"] == "function"
    assert names["render"] == "function"
    assert "path" in [i.imported_module for i in result.imports]


def test_source_parser_dispatches_by_extension(tmp_path):
    py = tmp_path / "app.py"
    py.write_text("def greet():\n    pass\n", encoding="utf-8")
    ts = tmp_path / "app.ts"
    ts.write_text("export function greet() {}\n", encoding="utf-8")

    parser = SourceParser()
    py_result = parser.parse(str(py))
    ts_result = parser.parse(str(ts))
    assert py_result.language == "python"
    assert ts_result.language == "typescript"
