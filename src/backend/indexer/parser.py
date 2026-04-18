"""Source parser support for Python and basic TypeScript/JavaScript.

Extracts:
- Symbols: classes, functions, async functions, methods, interfaces, types, enums.
- Imports: Python import/from-import and JS/TS import/export/require statements.
- Calls: function/method calls (for call-graph construction).

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
class RawCall:
    caller_qname: str
    callee_name: str


@dataclass
class ParsedFile:
    path: str
    language: str
    symbols: list[ParsedSymbol] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    calls: list[RawCall] = field(default_factory=list)
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
        self._extract_calls(result, source, lines, module_qname)
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

    def _extract_calls(self, result: ParsedFile, source: str, lines: list[str], module_qname: str) -> None:
        """Extract function/method calls from TS/JS source."""
        call_re = re.compile(r"(?:^|\s|[({,])(\w+)\s*\(")
        seen_calls: set[tuple[str, str, int]] = set()
        
        symbol_map = {s.name: s for s in result.symbols}
        
        for lineno, line in enumerate(lines, start=1):
            for match in call_re.finditer(line):
                callee_name = match.group(1)
                if callee_name in {"if", "for", "while", "switch", "catch", "function", "async", "class"}:
                    continue
                if callee_name not in symbol_map:
                    continue
                
                sym = symbol_map[callee_name]
                for caller_sym in result.symbols:
                    if caller_sym.symbol_type in {"function", "method"}:
                        key = (caller_sym.qualified_name, callee_name, lineno)
                        if key not in seen_calls:
                            seen_calls.add(key)
                            result.calls.append(
                                RawCall(caller_qname=caller_sym.qualified_name, callee_name=callee_name)
                            )

    @staticmethod
    def _language_for(path: Path) -> str:
        if path.suffix.lower() in {".ts", ".tsx"}:
            return "typescript"
        return "javascript"


class GoParser:
    """Parse Go source files."""

    _PACKAGE_RE = re.compile(r"package\s+(\w+)")
    _FUNC_RE = re.compile(r"func\s+(\w+)\s*\(")
    _STRUCT_RE = re.compile(r"type\s+(\w+)\s+struct\s*\{")
    _INTERFACE_RE = re.compile(r"type\s+(\w+)\s+interface\s*\{")
    _METHOD_RE = re.compile(r"func\s*\(\s*(\w+)\s+\*?(\w+)\s*\)\s+(\w+)\s*\(")
    _IMPORT_RE = re.compile(r'import\s+(?:"([^"]+)"|(?:\(\s*(?:[^)]+)\s*\)))')
    _IMPORT_BLOCK_RE = re.compile(r'import\s*\(\s*((?:[^)]+)+)\s*\)')

    def parse(self, file_path: str) -> ParsedFile:
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            lines = source.split("\n")
        except Exception as exc:
            return ParsedFile(path=file_path, language="go", parse_error=str(exc))

        module_qname = path_to_module(file_path)
        result = ParsedFile(path=file_path, language="go")

        # Extract package name
        for lineno, line in enumerate(lines, start=1):
            pkg_match = self._PACKAGE_RE.search(line)
            if pkg_match:
                pkg_name = pkg_match.group(1)
                module_qname = f"{module_qname}.{pkg_name}" if module_qname else pkg_name
                break

        # Extract symbols: structs, interfaces, functions
        self._append_matches(result, lines, module_qname, self._STRUCT_RE, "struct")
        self._append_matches(result, lines, module_qname, self._INTERFACE_RE, "interface")
        self._append_matches(result, lines, module_qname, self._FUNC_RE, "function")
        self._append_methods(result, lines, module_qname)

        # Extract imports
        self._extract_imports(result, source)

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

    def _append_methods(self, result: ParsedFile, lines: list[str], module_qname: str) -> None:
        """Extract method definitions (receiver type and method name)."""
        seen: set[tuple[str, str, int]] = set()
        for lineno, line in enumerate(lines, start=1):
            match = self._METHOD_RE.search(line)
            if not match:
                continue
            receiver_type = match.group(2)  # e.g., MyStruct
            method_name = match.group(3)    # e.g., DoSomething
            key = (receiver_type, method_name, lineno)
            if key in seen:
                continue
            seen.add(key)
            result.symbols.append(
                ParsedSymbol(
                    name=method_name,
                    qualified_name=f"{module_qname}.{receiver_type}.{method_name}",
                    symbol_type="method",
                    file_path=result.path,
                    line_start=lineno,
                    line_end=lineno,
                )
            )

    def _extract_imports(self, result: ParsedFile, source: str) -> None:
        """Extract Go imports."""
        for match in self._IMPORT_RE.finditer(source):
            import_path = match.group(1)
            if import_path:
                result.imports.append(
                    ParsedImport(source_path=result.path, imported_module=import_path)
                )

        for match in self._IMPORT_BLOCK_RE.finditer(source):
            block = match.group(1)
            for line in block.split("\n"):
                line = line.strip()
                if line and not line.startswith("//"):
                    import_path = line.strip('"\'')
                    if import_path:
                        result.imports.append(
                            ParsedImport(source_path=result.path, imported_module=import_path)
                        )


class RustParser:
    """Parse Rust source files."""

    _MOD_RE = re.compile(r"mod\s+(\w+)")
    _STRUCT_RE = re.compile(r"struct\s+(\w+)")
    _TRAIT_RE = re.compile(r"trait\s+(\w+)")
    _IMPL_RE = re.compile(r"impl\s+(?:<[^>]+>)?\s*(\w+)")
    _FUNC_RE = re.compile(r"fn\s+(\w+)\s*\(")
    _USE_RE = re.compile(r"use\s+([^\s;]+)")

    def parse(self, file_path: str) -> ParsedFile:
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            lines = source.split("\n")
        except Exception as exc:
            return ParsedFile(path=file_path, language="rust", parse_error=str(exc))

        module_qname = path_to_module(file_path)
        result = ParsedFile(path=file_path, language="rust")

        # Extract symbols: modules, structs, traits, impl blocks, functions
        self._append_matches(result, lines, module_qname, self._MOD_RE, "module")
        self._append_matches(result, lines, module_qname, self._STRUCT_RE, "struct")
        self._append_matches(result, lines, module_qname, self._TRAIT_RE, "trait")
        self._append_matches(result, lines, module_qname, self._IMPL_RE, "impl")
        self._append_matches(result, lines, module_qname, self._FUNC_RE, "function")

        # Extract imports
        for lineno, line in enumerate(lines, start=1):
            match = self._USE_RE.search(line)
            if match:
                import_path = match.group(1).rstrip(";")
                result.imports.append(
                    ParsedImport(source_path=result.path, imported_module=import_path)
                )

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


class JavaParser:
    """Parse Java source files."""

    _PACKAGE_RE = re.compile(r"package\s+([a-zA-Z0-9_.]+)\s*;")
    _CLASS_RE = re.compile(r"(?:public|private|protected)?\s*(?:static\s+)?class\s+(\w+)")
    _INTERFACE_RE = re.compile(r"(?:public|private|protected)?\s*interface\s+(\w+)")
    _ENUM_RE = re.compile(r"(?:public|private|protected)?\s*enum\s+(\w+)")
    _METHOD_RE = re.compile(r"(?:public|private|protected)?\s+(?:static\s+)?(?:\w+\s+)+(\w+)\s*\([^)]*\)")
    _IMPORT_RE = re.compile(r"import\s+([a-zA-Z0-9_.]+)\s*;")

    def parse(self, file_path: str) -> ParsedFile:
        path = Path(file_path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            lines = source.split("\n")
        except Exception as exc:
            return ParsedFile(path=file_path, language="java", parse_error=str(exc))

        module_qname = path_to_module(file_path)
        result = ParsedFile(path=file_path, language="java")

        # Extract package
        for lineno, line in enumerate(lines, start=1):
            pkg_match = self._PACKAGE_RE.search(line)
            if pkg_match:
                pkg_name = pkg_match.group(1)
                module_qname = pkg_name
                break

        # Extract symbols: classes, interfaces, enums
        self._append_matches(result, lines, module_qname, self._CLASS_RE, "class")
        self._append_matches(result, lines, module_qname, self._INTERFACE_RE, "interface")
        self._append_matches(result, lines, module_qname, self._ENUM_RE, "enum")
        self._append_class_methods(result, lines, module_qname)

        # Extract imports
        for lineno, line in enumerate(lines, start=1):
            match = self._IMPORT_RE.search(line)
            if match:
                import_path = match.group(1)
                result.imports.append(
                    ParsedImport(source_path=result.path, imported_module=import_path)
                )

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
        """Extract methods (simplified: look for method patterns within class context)."""
        class_stack: list[tuple[str, int]] = []
        brace_depth = 0

        for lineno, line in enumerate(lines, start=1):
            class_match = self._CLASS_RE.search(line)
            if class_match:
                class_name = class_match.group(1)
                current_depth = brace_depth + line.count("{") - line.count("}")
                class_stack.append((class_name, current_depth))
            elif class_stack:
                method_match = self._METHOD_RE.search(line)
                if method_match:
                    method_name = method_match.group(1)
                    if method_name not in {"if", "for", "while", "switch", "new"}:
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


class SourceParser:
    """Dispatch parser by file extension."""

    def __init__(self) -> None:
        self._python = PythonParser()
        self._ts_js = TypeScriptJavaScriptParser()
        self._go = GoParser()
        self._rust = RustParser()
        self._java = JavaParser()

    def parse(self, file_path: str) -> ParsedFile:
        suffix = Path(file_path).suffix.lower()
        if suffix == ".py":
            return self._python.parse(file_path)
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            return self._ts_js.parse(file_path)
        if suffix == ".go":
            return self._go.parse(file_path)
        if suffix == ".rs":
            return self._rust.parse(file_path)
        if suffix == ".java":
            return self._java.parse(file_path)
        return ParsedFile(path=file_path, language="unknown", parse_error="unsupported extension")


SUPPORTED_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java"}


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
