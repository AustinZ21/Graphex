"""File-content hash tracking for incremental indexing deduplication.

On each incremental run the pipeline compares the SHA-256 digest of a file
against the last-indexed digest stored on the File node in FalkorDB.
If the digest is unchanged the file is skipped entirely, saving graph writes
and keeping indexing throughput high.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(file_path: str) -> str:
    """Return the hex SHA-256 digest of *file_path* contents."""
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_changed(current_hash: str, stored_hash: str | None) -> bool:
    """Return True if the file must be re-indexed."""
    return stored_hash is None or current_hash != stored_hash
