"""Python source file parser using stdlib ast.

Extracts:
- Classes, functions, async functions, and methods as Symbol nodes.
- Import and from-import statements as potential IMPORTS edges.

Supports Python 3.11+ syntax. Falls back gracefully on SyntaxError.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class ParsedSymbol:
    name: str
    qualified_name: str
    symbol_type: str  # class | function | method | async_function | async_method
    file_path: str
    line_start: int
    line_end: int


@dataclass
class ParsedImport:
    source_path: str
    imported_module: str


@dataclass
class ParsedFile:
    path: str
    language: str
    symbols: list[ParsedSymbol] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    parse_error: str | None = None


class PythonParser:
    """Parse a single Python file and return structured symbol/import data."""

    def parse(self, file_path: str) -> ParsedFile:
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as exc:
            return ParsedFile(path=file_path, language="python", parse_error=str(exc))

        module_qname = self._path_to_module(file_path)
        result = ParsedFile(path=file_path, language="python")

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_qname = f"{module_qname}.{node.name}"
                result.symbols.append(
                    ParsedSymbol(
                        name=node.name,
                        qualified_name=class_qname,
                        symbol_type="class",
                        file_path=file_path,
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                    )
                )
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        kind = "async_method" if isinstance(item, ast.AsyncFunctionDef) else "method"
                        result.symbols.append(
                            ParsedSymbol(
                                name=item.name,
                                qualified_name=f"{class_qname}.{item.name}",
                                symbol_type=kind,
                                file_path=file_path,
                                line_start=item.lineno,
                                line_end=item.end_lineno or item.lineno,
                            )
                        )

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip methods (already handled inside ClassDef)
                parent = self._get_parent(tree, node)
                if isinstance(parent, ast.ClassDef):
                    continue
                kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                result.symbols.append(
                    ParsedSymbol(
                        name=node.name,
                        qualified_name=f"{module_qname}.{node.name}",
                        symbol_type=kind,
                        file_path=file_path,
                        line_start=node.lineno,
                        line_end=node.end_lineno or node.lineno,
                    )
                )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    result.imports.append(
                        ParsedImport(source_path=file_path, imported_module=alias.name)
                    )

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result.imports.append(
                        ParsedImport(source_path=file_path, imported_module=node.module)
                    )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _path_to_module(file_path: str) -> str:
        """Convert a filesystem path to a dotted module name."""
        p = Path(file_path)
        # Strip known root prefixes so qualified names stay readable
        try:
            rel = p.relative_to(Path(file_path).anchor)
        except ValueError:
            rel = p
        parts = [part for part in rel.parts if part not in ("src",)]
        module = ".".join(parts).removesuffix(".py")
        return module

    @staticmethod
    def _get_parent(tree: ast.AST, target: ast.AST) -> ast.AST | None:
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                if child is target:
                    return node
        return None


SUPPORTED_EXTENSIONS = {".py"}


def discover_files(repo_path: str) -> Iterator[str]:
    """Yield absolute paths of all supported source files under *repo_path*."""
    from pathlib import Path as _P
    import os

    skip_dirs = {
        ".git", ".venv", "venv", "env", "__pycache__",
        "node_modules", ".mypy_cache", ".pytest_cache", "dist", "build",
    }
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for fname in files:
            fpath = os.path.join(root, fname)
            if _P(fpath).suffix in SUPPORTED_EXTENSIONS:
                yield fpath
