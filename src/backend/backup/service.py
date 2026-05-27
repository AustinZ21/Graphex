"""Backup / restore service for the CGA auth PostgreSQL database.

Design goals
------------
* Online snapshots via ``pg_dump`` (no service interruption).
* Restore via ``psql`` against a transactional script.
* Configurable auto-backup loop (enabled / interval / retention).
* Pure-stdlib persistence of config to a JSON sidecar file.

Snapshot files are stored under ``backup_dir`` with names of the form
``auth-<UTC-ISO>.sql.gz`` (gzip-compressed plain-text dumps).  A
``auth-latest.sql.gz`` pointer is maintained for convenience.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class BackupError(Exception):
    """Raised for user-visible backup/restore failures."""


@dataclass
class BackupConfig:
    enabled: bool = True
    interval_minutes: int = 60
    keep_count: int = 24

    @classmethod
    def from_dict(cls, data: dict) -> "BackupConfig":
        return cls(
            enabled=bool(data.get("enabled", True)),
            interval_minutes=max(1, int(data.get("interval_minutes", 60))),
            keep_count=max(1, int(data.get("keep_count", 24))),
        )

    def to_dict(self) -> dict:
        return asdict(self)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pg_env_from_dsn(dsn: str) -> dict[str, str]:
    """Build the env dict that ``pg_dump`` / ``psql`` expect.

    asyncpg-style DSNs map cleanly onto PG* environment variables; using
    env vars avoids leaking the password into the process listing.
    """
    parsed = urlparse(dsn)
    env = os.environ.copy()
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    if parsed.username:
        env["PGUSER"] = parsed.username
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    db = (parsed.path or "").lstrip("/")
    if db:
        env["PGDATABASE"] = db
    return env


class BackupService:
    """Manage logical snapshots of the auth PostgreSQL database."""

    def __init__(self, dsn: str, backup_dir: str) -> None:
        self._dsn = dsn
        self._backup_dir = Path(backup_dir)
        self._config_path = self._backup_dir / "config.json"
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._config = self._load_config()
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._last_run_at: Optional[float] = None
        self._last_run_status: Optional[str] = None
        self._last_run_error: Optional[str] = None

    # ── config ────────────────────────────────────────────────────────────
    def _load_config(self) -> BackupConfig:
        if self._config_path.is_file():
            try:
                with self._config_path.open("r", encoding="utf-8") as fh:
                    return BackupConfig.from_dict(json.load(fh))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                log.warning("backup.config.load_failed", extra={"error": str(exc)})
        return BackupConfig()

    def _save_config(self) -> None:
        tmp = self._config_path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self._config.to_dict(), fh, indent=2)
        tmp.replace(self._config_path)

    def get_config(self) -> BackupConfig:
        return dataclasses.replace(self._config)

    def update_config(self, patch: dict) -> BackupConfig:
        merged = {**self._config.to_dict(), **(patch or {})}
        self._config = BackupConfig.from_dict(merged)
        self._save_config()
        return self.get_config()

    # ── snapshots ─────────────────────────────────────────────────────────
    def list_snapshots(self) -> list[dict]:
        items: list[dict] = []
        for path in sorted(self._backup_dir.glob("auth-*.sql.gz"), reverse=True):
            if path.name == "auth-latest.sql.gz":
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append(
                {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "format": "pg_dump",
                }
            )
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return items

    def snapshot_path(self, name: str) -> Path:
        # Allow only simple snapshot file names produced by us.
        if (
            not name
            or "/" in name
            or "\\" in name
            or not name.startswith("auth-")
            or not name.endswith(".sql.gz")
        ):
            raise BackupError("invalid snapshot name")
        path = (self._backup_dir / name).resolve()
        try:
            path.relative_to(self._backup_dir.resolve())
        except ValueError as exc:
            raise BackupError("invalid snapshot path") from exc
        if not path.is_file():
            raise BackupError("snapshot not found")
        return path

    async def run_backup(self, *, reason: str = "manual") -> dict:
        async with self._lock:
            return await asyncio.to_thread(self._do_backup_sync, reason)

    def _do_backup_sync(self, reason: str) -> dict:
        started = time.time()
        ts = _iso_now()
        target = self._backup_dir / f"auth-{ts}.sql.gz"
        tmp = target.with_suffix(".gz.tmp")
        env = _pg_env_from_dsn(self._dsn)
        # ``pg_dump --clean --if-exists`` produces a self-contained script
        # that can be replayed against an empty or existing database.
        cmd = [
            "pg_dump",
            "--no-owner",
            "--no-privileges",
            "--clean",
            "--if-exists",
            "--format=plain",
        ]
        try:
            with tmp.open("wb") as out:
                # Pipe pg_dump | gzip; we use gzip via Python for portability.
                import gzip

                with gzip.GzipFile(fileobj=out, mode="wb") as gz:
                    proc = subprocess.run(
                        cmd,
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                    if proc.returncode != 0:
                        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                        raise BackupError(f"pg_dump failed: {stderr or 'unknown error'}")
                    gz.write(proc.stdout)
            tmp.replace(target)
        except FileNotFoundError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            self._record_run(False, f"pg_dump not installed: {exc}")
            raise BackupError(f"pg_dump not installed: {exc}") from exc
        except BackupError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            self._record_run(False, "pg_dump failed")
            raise
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            self._record_run(False, str(exc))
            raise BackupError(f"backup write failed: {exc}") from exc

        # Maintain a stable "latest" pointer file.
        latest = self._backup_dir / "auth-latest.sql.gz"
        try:
            shutil.copyfile(target, latest)
        except OSError as exc:
            log.warning("backup.latest_update_failed", extra={"error": str(exc)})

        self._prune()
        self._record_run(True, None)
        return {
            "name": target.name,
            "size_bytes": target.stat().st_size,
            "duration_ms": int((time.time() - started) * 1000),
            "reason": reason,
        }

    def _prune(self) -> None:
        # Prune only the pg_dump-format snapshots; legacy SQLite snapshots
        # are left in place for the operator to manage manually.
        snapshots = sorted(
            self._backup_dir.glob("auth-2*.sql.gz"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        excess = snapshots[self._config.keep_count :]
        for path in excess:
            try:
                path.unlink()
            except OSError as exc:
                log.warning("backup.prune_failed", extra={"path": str(path), "error": str(exc)})

    def _record_run(self, ok: bool, error: Optional[str]) -> None:
        self._last_run_at = time.time()
        self._last_run_status = "ok" if ok else "error"
        self._last_run_error = error

    # ── restore ───────────────────────────────────────────────────────────
    async def restore(self, name: str) -> dict:
        async with self._lock:
            return await asyncio.to_thread(self._do_restore_sync, name)

    def _do_restore_sync(self, name: str) -> dict:
        src = self.snapshot_path(name)

        # Capture a pre-restore safety snapshot first.
        try:
            safety = self._do_backup_sync(reason="pre-restore-safety")
        except BackupError as exc:
            raise BackupError(f"failed to capture pre-restore safety dump: {exc}") from exc

        env = _pg_env_from_dsn(self._dsn)
        try:
            import gzip

            with gzip.open(src, "rb") as gz:
                script = gz.read()
            proc = subprocess.run(
                ["psql", "--quiet", "--no-psqlrc", "--single-transaction"],
                env=env,
                input=script,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if proc.returncode != 0:
                stderr = proc.stderr.decode("utf-8", errors="replace").strip()
                raise BackupError(f"psql restore failed: {stderr or 'unknown error'}")
        except FileNotFoundError as exc:
            raise BackupError(f"psql not installed: {exc}") from exc
        except OSError as exc:
            raise BackupError(f"restore failed: {exc}") from exc

        return {
            "restored_from": src.name,
            "pre_restore_snapshot": safety.get("name"),
            "note": "Restart the CGA service to ensure all components pick up the restored database.",
        }

    async def delete(self, name: str) -> None:
        path = self.snapshot_path(name)
        await asyncio.to_thread(path.unlink)

    # ── status ────────────────────────────────────────────────────────────
    def status(self) -> dict:
        # NOTE: ``db_path`` is preserved for frontend compatibility (the
        # admin UI reads ``status.db_path``); it now holds the redacted PG DSN.
        redacted = self._redact_dsn(self._dsn)
        return {
            "config": self._config.to_dict(),
            "dsn": redacted,
            "db_path": redacted,
            "backup_dir": str(self._backup_dir),
            "scheduler_running": bool(self._task and not self._task.done()),
            "last_run_at": (
                datetime.fromtimestamp(self._last_run_at, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
                if self._last_run_at
                else None
            ),
            "last_run_status": self._last_run_status,
            "last_run_error": self._last_run_error,
        }

    @staticmethod
    def _redact_dsn(dsn: str) -> str:
        try:
            parsed = urlparse(dsn)
        except ValueError:
            return dsn
        if not parsed.password:
            return dsn
        netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@", 1)
        return parsed._replace(netloc=netloc).geturl()

    # ── scheduler ─────────────────────────────────────────────────────────
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="cga-backup-scheduler")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self) -> None:
        # Short initial delay so app startup is not blocked.
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            return
        while True:
            try:
                if self._config.enabled:
                    try:
                        await self.run_backup(reason="scheduled")
                    except BackupError as exc:
                        log.warning("backup.scheduled_failed", extra={"error": str(exc)})
                    except Exception as exc:  # pragma: no cover - defensive
                        log.exception("backup.scheduled_crash", extra={"error": str(exc)})
                await asyncio.sleep(max(1, self._config.interval_minutes) * 60)
            except asyncio.CancelledError:
                return
