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
from backend.indexer.hasher import file_changed, sha256_file
from backend.indexer.parser import ParsedFile, SUPPORTED_EXTENSIONS, SourceParser, discover_files, path_to_module

log = structlog.get_logger()


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
        files = list(discover_files(repo_path))
        log.info("pipeline.full.start", repo_path=repo_path, files=len(files))
        self._upsert_repo(repo_path)
        stats: dict = {"files": 0, "skipped": 0, "symbols": 0, "calls": 0, "imports": 0, "errors": 0}
        symbol_map: dict[str, str] = {}
        for fpath in files:
            result = self._index_file(repo_path, fpath, symbol_map, force=True)
            self._accumulate(stats, result)
        stats["symbols"] = self._count_symbols()
        log.info("pipeline.full.done", **stats)
        return stats

    def index_incremental(self, repo_path: str, changed_paths: list[str]) -> dict:
        log.info("pipeline.incremental.start", changed=len(changed_paths))
        self._upsert_repo(repo_path)
        stats: dict = {"files": 0, "skipped": 0, "symbols": 0, "calls": 0, "imports": 0, "errors": 0}
        symbol_map = self._load_symbol_map()
        for fpath in changed_paths:
            if Path(fpath).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            result = self._index_file(repo_path, fpath, symbol_map, force=False)
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
        result = {"files": 0, "skipped": 0, "symbols": 0, "calls": 0, "imports": 0, "errors": 0}
        try:
            current_hash = sha256_file(file_path)
            if not force:
                stored = self._get_stored_hash(file_path)
                if not file_changed(current_hash, stored):
                    result["skipped"] = 1
                    return result

            parsed: ParsedFile = self._parser.parse(file_path)
            if parsed.parse_error:
                log.warning("pipeline.parse_error", path=file_path, error=parsed.parse_error)

            self._graph.query(
                S.MERGE_FILE,
                {"path": file_path, "language": parsed.language, "content_hash": current_hash},
            )
            self._graph.query(
                S.EDGE_REPO_CONTAINS_FILE,
                {"repo_path": repo_path, "file_path": file_path},
            )

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

            if parsed.language == "python":
                result["calls"] = self._write_python_call_edges(file_path, symbol_map)
            elif parsed.language in {"typescript", "javascript"}:
                result["calls"] = self._write_ts_js_call_edges(parsed.calls, symbol_map)
            
            result["imports"] = self._write_import_edges(file_path, parsed, repo_path)

            result["files"] = 1
        except Exception as exc:
            log.error("pipeline.file_error", path=file_path, error=str(exc))
            result["errors"] = 1
        return result

    def _write_python_call_edges(self, file_path: str, symbol_map: dict[str, str]) -> int:
        try:
            source = Path(file_path).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=file_path)
        except (SyntaxError, OSError):
            return 0

        module_qname = path_to_module(file_path)
        raw_calls: list[RawCall] = self._call_analyzer.extract(tree, file_path, module_qname)
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

    def _get_stored_hash(self, file_path: str) -> str | None:
        result = self._graph.query(S.QUERY_FILE_HASH, {"path": file_path})
        rows = result.result_set
        if rows and rows[0][0]:
            return rows[0][0]
        return None

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
