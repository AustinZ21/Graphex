"""Database backup and restore service for CGA.

Provides snapshot/restore of the auth SQLite database used to back the admin
plane (users, projects, audit logs, work briefings). Auto-backup runs as a
background task driven by configurable interval + retention.
"""

from backend.backup.service import BackupService, BackupConfig, BackupError

__all__ = ["BackupService", "BackupConfig", "BackupError"]
