"""Tests for file hash dedup (hasher.py)."""

import hashlib
import os
import tempfile

from backend.indexer.hasher import sha256_file, file_changed


def test_sha256_stable(tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("print('hello')", encoding="utf-8")
    h1 = sha256_file(str(f))
    h2 = sha256_file(str(f))
    assert h1 == h2
    assert len(h1) == 64


def test_sha256_changes_on_edit(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("x = 1", encoding="utf-8")
    h1 = sha256_file(str(f))
    f.write_text("x = 2", encoding="utf-8")
    h2 = sha256_file(str(f))
    assert h1 != h2


def test_file_changed_no_stored():
    assert file_changed("abc", None) is True


def test_file_changed_same():
    assert file_changed("abc", "abc") is False


def test_file_changed_different():
    assert file_changed("abc", "xyz") is True
