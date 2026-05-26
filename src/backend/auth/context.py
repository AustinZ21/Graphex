from __future__ import annotations

from contextvars import ContextVar


_current_project_external_id: ContextVar[str] = ContextVar(
    "current_project_external_id",
    default="",
)

_current_project_db_id: ContextVar[int] = ContextVar(
    "current_project_db_id",
    default=0,
)