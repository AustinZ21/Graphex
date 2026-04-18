"""Indexing pipeline – orchestrates parsing and graph writes.

Full index   : scan the entire repo, upsert all entities.
Incremental  : re-index only the changed file paths, skipping hash-unchanged files.

Phase 2 additions:
- File-hash dedup: skip unchanged files on incremental runs.
- Call-graph extraction: write CALLS edges between symbol nodes.

All graph writes use MERGE so re-indexing is safe and idempotent.
"""

from __future__ import annotations

import ast
from pathlib import Path

import structlog

from backend.graph.client import GraphClient
from backend.graph import schema as S
from backend.indexer.parser import PythonParser, ParsedFile, discover_files
from backend.indexer.hasher import sha256_file, file_changed
from backend.indexer.call_analyzer import CallAnalyzer, RawCall

log = structlog.get_logger()


class IndexPipeline:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph
        self._parser = PythonParser()
        self._call_analyzer = CallAnalyzer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_full(self, repo_path: str) -> dict:
        files = list(discover_files(repo_path))
        log.info("pipeline.full.start", repo_path=repo_path, files=len(files))
        self._upsert_repo(repo_path)
        stats: dict = {"files": 0, "skipped": 0, "symbols": 0, "calls": 0, "errors": 0}
        symbol_map: dict[str, str] = {}  # name → qualified_name (for call resolution)
        for fpath in files:
            result = self._index_file(repo_path, fpath, symbol_map, force=True)
            self._accumulate(stats, result)
        stats["symbols"] = self._count_symbols()
        log.info("pipeline.full.done", **stats)
        return stats

    def index_incremental(self, repo_path: str, changed_paths: list[str]) -> dict:
        log.info("pipeline.incremental.start", changed=len(changed_paths))
        self._upsert_repo(repo_path)
        stats: dict = {"files": 0, "skipped": 0, "symbols": 0, "calls": 0, "errors": 0}
        symbol_map = self._load_symbol_map()
        for fpath in changed_paths:
            if Path(fpath).suffix not in SUPPORTED_EXTENSIONS:
                continue
            result = self._index_file(repo_path, fpath, symbol_map, force=False)
            self._accumulate(stats, result)
        stats["symbols"] = self._count_symbols()
        log.info("pipeline.incremental.done", **stats)
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
        result = {"files": 0, "skipped": 0, "symbols": 0, "calls": 0, "errors": 0}
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

            # Phase 2: extract and write call graph edges
            calls_written = self._write_call_edges(file_path, parsed, symbol_map)
            result["calls"] = calls_written
            result["files"] = 1
        except Exception as exc:
            log.error("pipeline.file_error", path=file_path, error=str(exc))
            result["errors"] = 1
        return result

    def _write_call_edges(
        self, file_path: str, parsed: ParsedFile, symbol_map: dict[str, str]
    ) -> int:
        """Parse AST for call sites and write CALLS edges where resolvable."""
        try:
            from pathlib import Path as _P
            source = _P(file_path).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=file_path)
        except (SyntaxError, OSError):
            return 0

        module_qname = PythonParser._path_to_module(file_path)
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

    def _get_stored_hash(self, file_path: str) -> str | None:
        result = self._graph.query(S.QUERY_FILE_HASH, {"path": file_path})
        rows = result.result_set
        if rows and rows[0][0]:
            return rows[0][0]
        return None

    def _load_symbol_map(self) -> dict[str, str]:
        """Load name→qualified_name mapping from the graph for call resolution."""
        try:
            result = self._graph.query(
                "MATCH (s:Symbol) RETURN s.name, s.qualified_name LIMIT 100000"
            )
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



class IndexPipeline:
    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph
        self._parser = PythonParser()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_full(self, repo_path: str) -> dict:
        files = list(discover_files(repo_path))
        log.info("pipeline.full.start", repo_path=repo_path, files=len(files))
        self._upsert_repo(repo_path)
        stats = {"files": 0, "symbols": 0, "errors": 0}
        for fpath in files:
            ok = self._index_file(repo_path, fpath)
            if ok:
                stats["files"] += 1
            else:
                stats["errors"] += 1
        stats["symbols"] = self._count_symbols()
        log.info("pipeline.full.done", **stats)
        return stats

    def index_incremental(self, repo_path: str, changed_paths: list[str]) -> dict:
        from pathlib import Path
        from backend.indexer.parser import SUPPORTED_EXTENSIONS

        log.info("pipeline.incremental.start", changed=len(changed_paths))
        self._upsert_repo(repo_path)
        stats = {"files": 0, "symbols": 0, "errors": 0}
        for fpath in changed_paths:
            if Path(fpath).suffix not in SUPPORTED_EXTENSIONS:
                continue
            ok = self._index_file(repo_path, fpath)
            if ok:
                stats["files"] += 1
            else:
                stats["errors"] += 1
        stats["symbols"] = self._count_symbols()
        log.info("pipeline.incremental.done", **stats)
        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upsert_repo(self, repo_path: str) -> None:
        from pathlib import Path
        name = Path(repo_path).name
        self._graph.query(S.MERGE_REPO, {"path": repo_path, "name": name})

    def _index_file(self, repo_path: str, file_path: str) -> bool:
        try:
            parsed: ParsedFile = self._parser.parse(file_path)
            if parsed.parse_error:
                log.warning("pipeline.parse_error", path=file_path, error=parsed.parse_error)

            self._graph.query(S.MERGE_FILE, {"path": file_path, "language": parsed.language})
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
            return True
        except Exception as exc:
            log.error("pipeline.file_error", path=file_path, error=str(exc))
            return False

    def _count_symbols(self) -> int:
        result = self._graph.query(S.QUERY_COUNT_SYMBOLS)
        rows = result.result_set
        return rows[0][0] if rows else 0
