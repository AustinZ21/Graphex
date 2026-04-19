from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobType(str, Enum):
    INDEX_FULL = "index_full"
    INDEX_INCREMENTAL = "index_incremental"


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class IndexJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_type: JobType
    repo_path: str
    changed_paths: Optional[list[str]] = None
    project_key: Optional[str] = None  # FalkorDB graph name for this project
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
