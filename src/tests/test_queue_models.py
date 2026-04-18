"""Unit tests for queue message models."""

from __future__ import annotations

import pytest

from backend.queue.models import IndexJob, JobType, JobStatus


def test_index_full_job_defaults():
    job = IndexJob(job_type=JobType.INDEX_FULL, repo_path="/repo/myproject")
    assert job.job_type == JobType.INDEX_FULL
    assert job.repo_path == "/repo/myproject"
    assert job.changed_paths is None
    assert len(job.job_id) == 36  # UUID4
    assert "T" in job.created_at  # ISO timestamp


def test_index_incremental_job():
    job = IndexJob(
        job_type=JobType.INDEX_INCREMENTAL,
        repo_path="/repo/myproject",
        changed_paths=["src/a.py", "src/b.py"],
    )
    assert job.job_type == JobType.INDEX_INCREMENTAL
    assert job.changed_paths == ["src/a.py", "src/b.py"]


def test_job_round_trip_json():
    job = IndexJob(
        job_type=JobType.INDEX_INCREMENTAL,
        repo_path="/repo",
        changed_paths=["x.py"],
    )
    restored = IndexJob.model_validate_json(job.model_dump_json())
    assert restored.job_id == job.job_id
    assert restored.job_type == job.job_type
    assert restored.changed_paths == job.changed_paths


def test_job_status_enum():
    assert JobStatus.PENDING == "pending"
    assert JobStatus.DONE == "done"
