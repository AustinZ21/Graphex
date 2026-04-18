"""Source parser support for Python and basic TypeScript/JavaScript.

Extracts:
- Symbols: classes, functions, async functions, methods, interfaces, types, enums.
- Imports: Python import/from-import and JS/TS import/export/require statements.

Python parsing uses stdlib ast.
TypeScript/JavaScript parsing uses lightweight regex-based extraction for
project-wide indexing without requiring language-specific parser packages.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class ParsedSymbol:
    name: str
    qualified_name: str
    symbol_type: str
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


def path_to_module(file_path: str) -> str:
    p = Path(file_path)
    try:
        rel = p.relative_to(Path(file_path).anchor)
    except ValueError:
        rel = p
    parts = [part for part in rel.parts if part not in ("src",)]
    module = ".".join(parts)
    for suffix in (".py", ".ts", ".tsx", ".js", ".jsx"):
        if module.endswith(suffix):
            module = module[: -len(suffix)]
            break
    return module


class PythonParser:
    """Parse a Python file and return structured symbol/import data."""

    def parse(self, file_path: str) -> ParsedFile:
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as exc:
            return ParsedFile(path=file_path, language="python", parse_error=str(exc))

        module_qname = path_to_module(file_path)
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
                    result.imports.append(ParsedImport(source_path=file_path, imported_module=alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result.imports.append(ParsedImport(source_path=file_path, imported_module=node.module))

        return result

    @staticmethod
    def _get_parent(tree: ast.AST, target: ast.AST) -> ast.AST | None:
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                if child is target:
                    return node
        return None


class TypeScriptJavaScriptParser:
    """Regex-based parser for basic TS/JS indexing support."""

    _IMPORT_FROM_RE = re.compile(r"^\s*(?:import|export)\b.*?from\s+[\"']([^\"']+)[\"']", re.MULTILINE)
    _IMPORT_SIDE_EFFECT_RE = re.compile(r"^\s*import\s+[\"']([^\"']+)[\"']", re.MULTILINE)
    _REQUIRE_RE = re.compile(r"require\(\s*[\"']([^\"']+)[\"']\s*\)")
    _CLASS_RE = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)", re.MULTILINE)
    _INTERFACE_RE = re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)", re.MULTILINE)
    _TYPE_RE = re.compile(r"^\s*(?:export\s+)?type\s+(\w+)\s*=", re.MULTILINE)
    _ENUM_RE = re.compile(r"^\s*(?:export\s+)?enum\s+(\w+)", re.MULTILINE)
    _FUNCTION_RE = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(", re.MULTILINE)
    _ARROW_RE = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^\)]*\)|\w+)\s*=>",
        re.MULTILINE,
    )

    def parse(self, file_path: str) -> ParsedFile:
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ParsedFile(path=file_path, language=self._language_for(path), parse_error=str(exc))

        module_qname = path_to_module(file_path)
        result = ParsedFile(path=file_path, language=self._language_for(path))
        lines = source.splitlines()

        for imported_module in self._extract_imports(source):
            result.imports.append(ParsedImport(source_path=file_path, imported_module=imported_module))

        self._append_matches(result, lines, module_qname, self._CLASS_RE, "class")
        self._append_matches(result, lines, module_qname, self._INTERFACE_RE, "interface")
        self._append_matches(result, lines, module_qname, self._TYPE_RE, "type")
        self._append_matches(result, lines, module_qname, self._ENUM_RE, "enum")
        self._append_matches(result, lines, module_qname, self._FUNCTION_RE, "function")
        self._append_matches(result, lines, module_qname, self._ARROW_RE, "function")
        self._append_class_methods(result, lines, module_qname)
        return result

    def _append_matches(
        self,
        result: ParsedFile,
        lines: list[str],
        module_qname: str,
        pattern: re.Pattern[str],
        symbol_type: str,
    ) -> None:
        seen: set[tuple[str, int]] = set()
        for lineno, line in enumerate(lines, start=1):
            match = pattern.search(line)
            if not match:
                continue
            name = match.group(1)
            key = (name, lineno)
            if key in seen:
                continue
            seen.add(key)
            result.symbols.append(
                ParsedSymbol(
                    name=name,
                    qualified_name=f"{module_qname}.{name}",
                    symbol_type=symbol_type,
                    file_path=result.path,
                    line_start=lineno,
                    line_end=lineno,
                )
            )

    def _append_class_methods(self, result: ParsedFile, lines: list[str], module_qname: str) -> None:
        class_stack: list[tuple[str, int]] = []
        brace_depth = 0
        method_re = re.compile(r"^\s*(?:async\s+)?(\w+)\s*\([^\)]*\)\s*\{")

        for lineno, line in enumerate(lines, start=1):
            class_match = self._CLASS_RE.search(line)
            if class_match:
                class_name = class_match.group(1)
                current_depth = brace_depth + line.count("{") - line.count("}")
                class_stack.append((class_name, max(1, current_depth)))
            elif class_stack:
                method_match = method_re.search(line)
                if method_match:
                    method_name = method_match.group(1)
                    if method_name != "constructor":
                        class_name = class_stack[-1][0]
                        result.symbols.append(
                            ParsedSymbol(
                                name=method_name,
                                qualified_name=f"{module_qname}.{class_name}.{method_name}",
                                symbol_type="method",
                                file_path=result.path,
                                line_start=lineno,
                                line_end=lineno,
                            )
                        )

            brace_depth += line.count("{") - line.count("}")
            while class_stack and brace_depth < class_stack[-1][1]:
                class_stack.pop()

    def _extract_imports(self, source: str) -> list[str]:
        imports: list[str] = []
        imports.extend(self._IMPORT_FROM_RE.findall(source))
        imports.extend(self._IMPORT_SIDE_EFFECT_RE.findall(source))
        imports.extend(self._REQUIRE_RE.findall(source))
        return imports

    @staticmethod
    def _language_for(path: Path) -> str:
        if path.suffix.lower() in {".ts", ".tsx"}:
            return "typescript"
        return "javascript"


class SourceParser:
    """Dispatch parser by file extension."""

    def __init__(self) -> None:
        self._python = PythonParser()
        self._ts_js = TypeScriptJavaScriptParser()

    def parse(self, file_path: str) -> ParsedFile:
        suffix = Path(file_path).suffix.lower()
        if suffix == ".py":
            return self._python.parse(file_path)
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            return self._ts_js.parse(file_path)
        return ParsedFile(path=file_path, language="unknown", parse_error="unsupported extension")


SUPPORTED_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}


def discover_files(repo_path: str) -> Iterator[str]:
    """Yield absolute paths of all supported source files under *repo_path*."""
    import os

    skip_dirs = {
        ".git", ".venv", "venv", "env", "__pycache__",
        "node_modules", ".mypy_cache", ".pytest_cache", "dist", "build",
        ".next", "coverage",
    }
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for fname in files:
            fpath = os.path.join(root, fname)
            if Path(fpath).suffix.lower() in SUPPORTED_EXTENSIONS:
                yield fpath
