"""Indexing pipeline – orchestrates parsing and graph writes.

Full index   : scan the entire repo, upsert all entities.
Incremental  : re-index only the changed file paths.

All graph writes use MERGE so re-indexing is safe and idempotent.
"""

from __future__ import annotations

import structlog

from backend.graph.client import GraphClient
from backend.graph import schema as S
from backend.indexer.parser import PythonParser, ParsedFile, discover_files

log = structlog.get_logger()


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
