"""Indexing pipeline – orchestrates parsing and graph writes.

Full index   : scan the entire repo, upsert all entities.
Incremental  : re-index only the changed file paths, skipping hash-unchanged files.

Python supports CALLS edge extraction.
TS/JS support currently indexes files, symbols, and imports for repository-wide lookup.

Import tracking: resolve local imports (./utils, ../core) to actual file paths and write IMPORTS edges.

All graph writes use MERGE so re-indexing is safe and idempotent.
"""

from __future__ import annotations

import ast
from pathlib import Path

import structlog

from backend.graph.client import GraphClient
from backend.graph import schema as S
from backend.indexer.call_analyzer import CallAnalyzer, RawCall
from backend.indexer.hasher import file_changed, hash_variable_flows, sha256_file
from backend.indexer.parser import ParsedFile, SUPPORTED_EXTENSIONS, SourceParser, discover_files, path_to_module

log = structlog.get_logger()


def _normalize_repo_path(repo_path: str) -> str:
    """Return an indexable repo path in both host and container runtimes.

    In Docker dev, Windows-style paths (e.g. D:/Repos/OSAgent) are not directly
    visible. We map them to /repos/<name> when that path exists.
    """
    candidate = Path(repo_path)
    if candidate.exists():
        return str(candidate)

    normalized = repo_path.replace("\\", "/")
    marker = "/Repos/"
    idx = normalized.find(marker)
    if idx >= 0:
        tail = normalized[idx + len(marker):].strip("/")
        mapped = Path("/repos") / tail
        if mapped.exists():
            return str(mapped)

    return repo_path


def _resolve_import_path(source_file: str, imported_module: str, repo_path: str) -> str | None:
    """Resolve relative import to actual file path (best effort).
    
    Handles:
    - Relative paths like "./utils", "../core"
    - Directory imports like "./handlers/auth"
    - Language-specific extensions
    
    Returns the resolved file path if found, None otherwise (e.g., external packages).
    """
    source_path = Path(source_file)
    source_dir = source_path.parent
    repo = Path(repo_path)
    
    if imported_module.startswith("."):
        if imported_module.startswith("./"):
            rel = imported_module[2:]
        elif imported_module.startswith("../"):
            rel = imported_module
        else:
            rel = imported_module[1:]
        
        candidate = (source_dir / rel).resolve()
        
        if candidate.is_file():
            return str(candidate)
        
        for ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
            file_candidate = Path(str(candidate) + ext)
            if file_candidate.is_file():
                return str(file_candidate)
        
        if candidate.is_dir():
            for ext in [".py", ".ts", ".tsx", ".js", ".jsx"]:
                init_file = candidate / f"__init__{ext}" if ext == ".py" else candidate / f"index{ext}"
                if init_file.is_file():
                    return str(init_file)
    
    return None



class IndexPipeline:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph
        self._parser = SourceParser()
        self._call_analyzer = CallAnalyzer()

    def index_full(self, repo_path: str) -> dict:
        resolved_repo_path = _normalize_repo_path(repo_path)
        files = list(discover_files(resolved_repo_path))
        log.info("pipeline.full.start", repo_path=repo_path, resolved_repo_path=resolved_repo_path, files=len(files))
        self._upsert_repo(repo_path)
        stats: dict = {"files": 0, "skipped": 0, "symbols": 0, "calls": 0, "imports": 0, "variables": 0, "variable_flows": 0, "errors": 0}
        symbol_map: dict[str, str] = {}
        for fpath in files:
            result = self._index_file(repo_path, fpath, symbol_map, force=True)
            self._accumulate(stats, result)
        stats["symbols"] = self._count_symbols()
        log.info("pipeline.full.done", **stats)
        return stats

    def index_incremental(self, repo_path: str, changed_paths: list[str]) -> dict:
        resolved_repo_path = _normalize_repo_path(repo_path)
        log.info("pipeline.incremental.start", changed=len(changed_paths), repo_path=repo_path, resolved_repo_path=resolved_repo_path)
        self._upsert_repo(repo_path)
        stats: dict = {"files": 0, "skipped": 0, "symbols": 0, "calls": 0, "imports": 0, "variables": 0, "variable_flows": 0, "errors": 0}
        symbol_map = self._load_symbol_map()
        for fpath in changed_paths:
            normalized_fpath = fpath
            if not Path(normalized_fpath).exists():
                rel = Path(fpath).as_posix().replace("\\", "/")
                if rel.startswith("D:/Repos/"):
                    rel = rel[len("D:/Repos/"):]
                mapped_file = Path("/repos") / rel
                normalized_fpath = str(mapped_file)

            if Path(normalized_fpath).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            result = self._index_file(repo_path, normalized_fpath, symbol_map, force=False)
            self._accumulate(stats, result)
        stats["symbols"] = self._count_symbols()
        log.info("pipeline.incremental.done", **stats)
        return stats

    def _upsert_repo(self, repo_path: str) -> None:
        name = Path(repo_path).name
        self._graph.query(S.MERGE_REPO, {"path": repo_path, "name": name})

    def _index_file(
        self,
        repo_path: str,
        file_path: str,
        symbol_map: dict[str, str],
        force: bool,
    ) -> dict:
        result = {"files": 0, "skipped": 0, "symbols": 0, "calls": 0, "imports": 0, "variables": 0, "variable_flows": 0, "errors": 0}
        try:
            from backend.indexer.hasher import hash_symbols, hash_calls, hash_imports
            
            current_hash = sha256_file(file_path)
            if not force:
                stored = self._get_stored_hash(file_path)
                if not file_changed(current_hash, stored):
                    result["skipped"] = 1
                    return result

            parsed: ParsedFile = self._parser.parse(file_path)
            if parsed.parse_error:
                log.warning("pipeline.parse_error", path=file_path, error=parsed.parse_error)

            current_symbols_hash = hash_symbols(parsed)
            current_calls_hash = hash_calls(parsed)
            current_imports_hash = hash_imports(parsed)
            current_variables_hash = hash_variable_flows(parsed)
            
            stored_hashes = self._get_stored_symbol_hashes(file_path) if not force else {}
            symbols_changed = stored_hashes.get("symbols_hash") != current_symbols_hash
            calls_changed = stored_hashes.get("calls_hash") != current_calls_hash
            imports_changed = stored_hashes.get("imports_hash") != current_imports_hash
            variables_changed = stored_hashes.get("variables_hash") != current_variables_hash

            self._graph.query(
                S.MERGE_FILE,
                {
                    "path": file_path,
                    "language": parsed.language,
                    "content_hash": current_hash,
                    "symbols_hash": current_symbols_hash,
                    "calls_hash": current_calls_hash,
                    "imports_hash": current_imports_hash,
                    "variables_hash": current_variables_hash,
                },
            )
            self._graph.query(
                S.EDGE_REPO_CONTAINS_FILE,
                {"repo_path": repo_path, "file_path": file_path},
            )

            if symbols_changed:
                for sym in parsed.symbols:
                    self._graph.query(
                        S.MERGE_SYMBOL,
                        {
                            "qualified_name": sym.qualified_name,
                            "name": sym.name,
                            "symbol_type": sym.symbol_type,
                            "file_path": sym.file_path,
                            "line_start": sym.line_start,
                            "line_end": sym.line_end,
                        },
                    )
                    self._graph.query(
                        S.EDGE_FILE_DEFINES_SYMBOL,
                        {"file_path": file_path, "qualified_name": sym.qualified_name},
                    )
                    symbol_map[sym.name] = sym.qualified_name
                    result["symbols"] += 1

            python_raw_calls: list[RawCall] = []
            if parsed.language == "python" and (calls_changed or variables_changed):
                python_raw_calls = self._extract_python_raw_calls(file_path)

            if calls_changed:
                if parsed.language == "python":
                    result["calls"] = self._write_python_call_edges(python_raw_calls, symbol_map)
                elif parsed.language in {"typescript", "javascript"}:
                    result["calls"] = self._write_ts_js_call_edges(parsed.calls, symbol_map)

            if imports_changed:
                result["imports"] = self._write_import_edges(file_path, parsed, repo_path)

            if variables_changed:
                variable_stats = self._write_variable_flow_edges(parsed)
                result["variables"] = variable_stats["variables"]
                result["variable_flows"] = variable_stats["variable_flows"]

            if calls_changed or variables_changed:
                if parsed.language == "python":
                    result["variable_flows"] += self._write_cross_scope_variable_flows(python_raw_calls, symbol_map)
                elif parsed.language in {"typescript", "javascript"}:
                    result["variable_flows"] += self._write_cross_scope_variable_flows(parsed.calls, symbol_map)

            if symbols_changed or calls_changed or imports_changed or variables_changed:
                result["files"] = 1
            else:
                result["skipped"] = 1
        except Exception as exc:
            log.error("pipeline.file_error", path=file_path, error=str(exc))
            result["errors"] = 1
        return result

    def _extract_python_raw_calls(self, file_path: str) -> list[RawCall]:
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=file_path)
        except (SyntaxError, OSError):
            return []

        module_qname = path_to_module(file_path)
        return self._call_analyzer.extract(tree, file_path, module_qname)

    def _write_python_call_edges(self, raw_calls: list[RawCall], symbol_map: dict[str, str]) -> int:
        written = 0
        for rc in raw_calls:
            callee_qname = symbol_map.get(rc.callee_name)
            if callee_qname and callee_qname != rc.caller_qname:
                try:
                    self._graph.query(
                        S.EDGE_SYMBOL_CALLS,
                        {"caller_qname": rc.caller_qname, "callee_qname": callee_qname},
                    )
                    written += 1
                except Exception:
                    pass
        return written

    def _write_ts_js_call_edges(self, raw_calls: list[RawCall], symbol_map: dict[str, str]) -> int:
        """Write CALLS edges for TS/JS calls."""
        written = 0
        for rc in raw_calls:
            callee_qname = symbol_map.get(rc.callee_name)
            if callee_qname and callee_qname != rc.caller_qname:
                try:
                    self._graph.query(
                        S.EDGE_SYMBOL_CALLS,
                        {"caller_qname": rc.caller_qname, "callee_qname": callee_qname},
                    )
                    written += 1
                except Exception:
                    pass
        return written

    def _write_import_edges(self, file_path: str, parsed: ParsedFile, repo_path: str) -> int:
        """Resolve and write IMPORTS edges for local imports."""
        written = 0
        for imp in parsed.imports:
            target_path = _resolve_import_path(file_path, imp.imported_module, repo_path)
            if target_path:
                try:
                    self._graph.query(
                        S.EDGE_FILE_IMPORTS,
                        {"src_path": file_path, "target_path": target_path},
                    )
                    written += 1
                except Exception:
                    pass
        return written

    def _write_variable_flow_edges(self, parsed: ParsedFile) -> dict[str, int]:
        stats = {"variables": 0, "variable_flows": 0}
        for variable in parsed.variables:
            try:
                self._graph.query(
                    S.MERGE_VARIABLE,
                    {
                        "qualified_name": variable.qualified_name,
                        "name": variable.name,
                        "scope_qname": variable.scope_qname,
                        "file_path": variable.file_path,
                        "line_number": variable.line_number,
                        "role": variable.role,
                    },
                )
                self._graph.query(
                    S.EDGE_SYMBOL_HAS_VARIABLE,
                    {"scope_qname": variable.scope_qname, "variable_qname": variable.qualified_name},
                )
                stats["variables"] += 1
            except Exception:
                pass

        for flow in parsed.variable_flows:
            try:
                self._graph.query(
                    S.EDGE_VARIABLE_FLOWS,
                    {
                        "source_qname": flow.source_qname,
                        "target_qname": flow.target_qname,
                        "scope_qname": flow.scope_qname,
                        "line_number": flow.line_number,
                        "flow_type": flow.flow_type,
                    },
                )
                stats["variable_flows"] += 1
            except Exception:
                pass
        return stats

    def _write_cross_scope_variable_flows(self, raw_calls: list[RawCall], symbol_map: dict[str, str]) -> int:
        written = 0
        parameter_cache: dict[str, list[str]] = {}
        for call in raw_calls:
            callee_qname = symbol_map.get(call.callee_name)
            if not callee_qname:
                continue

            if callee_qname not in parameter_cache:
                parameter_cache[callee_qname] = self._get_scope_parameter_qnames(callee_qname)

            callee_params = parameter_cache[callee_qname]
            arg_names = call.arg_names or []
            for index, arg_name in enumerate(arg_names[: len(callee_params)]):
                source_qname = f"{call.caller_qname}:{arg_name}"
                target_qname = callee_params[index]
                try:
                    self._graph.query(
                        S.EDGE_VARIABLE_FLOWS,
                        {
                            "source_qname": source_qname,
                            "target_qname": target_qname,
                            "scope_qname": call.caller_qname,
                            "line_number": 0,
                            "flow_type": "argument",
                        },
                    )
                    written += 1
                except Exception:
                    pass

            if call.result_var_name:
                source_qname = f"{callee_qname}:__return__"
                target_qname = f"{call.caller_qname}:{call.result_var_name}"
                try:
                    self._graph.query(
                        S.EDGE_VARIABLE_FLOWS,
                        {
                            "source_qname": source_qname,
                            "target_qname": target_qname,
                            "scope_qname": call.caller_qname,
                            "line_number": 0,
                            "flow_type": "call_return",
                        },
                    )
                    written += 1
                except Exception:
                    pass
        return written

    def _get_scope_parameter_qnames(self, scope_qname: str) -> list[str]:
        try:
            result = self._graph.query(
                "MATCH (:Symbol {qualified_name: $scope_qname})-[:USES_VARIABLE]->(v:Variable {role: 'parameter'}) RETURN v.qualified_name ORDER BY v.line_number, v.name",
                {"scope_qname": scope_qname},
            )
            return [row[0] for row in result.result_set if row and row[0]]
        except Exception:
            return []

    def _get_stored_hash(self, file_path: str) -> str | None:
        result = self._graph.query(S.QUERY_FILE_HASH, {"path": file_path})
        rows = result.result_set
        if rows and rows[0][0]:
            return rows[0][0]
        return None

    def _get_stored_symbol_hashes(self, file_path: str) -> dict[str, str]:
        """Get stored symbol-level hashes for fine-grained incremental tracking."""
        try:
            result = self._graph.query(S.QUERY_FILE_SYMBOL_HASHES, {"path": file_path})
            if result.result_set and len(result.result_set[0]) >= 5:
                row = result.result_set[0]
                return {
                    "content_hash": row[0],
                    "symbols_hash": row[1],
                    "calls_hash": row[2],
                    "imports_hash": row[3],
                    "variables_hash": row[4],
                }
        except Exception:
            pass
        return {}

    def _load_symbol_map(self) -> dict[str, str]:
        try:
            result = self._graph.query("MATCH (s:Symbol) RETURN s.name, s.qualified_name LIMIT 100000")
            return {row[0]: row[1] for row in result.result_set if row[0]}
        except Exception:
            return {}

    def _count_symbols(self) -> int:
        result = self._graph.query(S.QUERY_COUNT_SYMBOLS)
        rows = result.result_set
        return rows[0][0] if rows else 0

    @staticmethod
    def _accumulate(total: dict, partial: dict) -> None:
        for k, v in partial.items():
            total[k] = total.get(k, 0) + v
