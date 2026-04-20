"""MCP-side job producer.

MCP tool handlers call this to enqueue indexing jobs into the Redis Stream.
Decouples tool response time from actual indexing work.
"""

from __future__ import annotations

import asyncio
import time

from backend.queue.streams import JobProducer
from backend.queue.models import IndexJob, JobType


class MCPProducer:
    def __init__(self, redis_url: str) -> None:
        self._producer = JobProducer(redis_url=redis_url)

    async def connect(self) -> None:
        await self._producer.connect()

    async def close(self) -> None:
        await self._producer.close()

    async def submit_full_index(
        self, repo_path: str, project_name: str | None = None
    ) -> dict[str, str]:
        job = IndexJob(
            job_type=JobType.INDEX_FULL,
            repo_path=repo_path,
            project_name=project_name,
        )
        stream_id = await self._producer.publish(job)
        return {"job_id": job.job_id, "stream_id": stream_id}

    async def submit_incremental_index(
        self, repo_path: str, changed_paths: list[str], project_name: str | None = None
    ) -> dict[str, str]:
        job = IndexJob(
            job_type=JobType.INDEX_INCREMENTAL,
            repo_path=repo_path,
            changed_paths=changed_paths,
            project_name=project_name,
        )
        stream_id = await self._producer.publish(job)
        return {"job_id": job.job_id, "stream_id": stream_id}

    async def get_job_status(self, job_id: str) -> dict | None:
        return await self._producer.get_job_status(job_id)

    async def wait_for_job_status(
        self,
        job_id: str,
        timeout_sec: float = 120.0,
        poll_interval_sec: float = 1.0,
    ) -> dict:
        deadline = time.monotonic() + max(0.0, timeout_sec)
        interval = max(0.1, poll_interval_sec)

        while True:
            status = await self.get_job_status(job_id)
            if status is None:
                if time.monotonic() >= deadline:
                    return {
                        "job_id": job_id,
                        "status": "not_found",
                        "ready": False,
                        "timeout": True,
                    }
                await asyncio.sleep(interval)
                continue

            state = str(status.get("status", ""))
            if state in {"done", "failed"}:
                return {
                    **status,
                    "ready": True,
                    "timeout": False,
                }

            if time.monotonic() >= deadline:
                return {
                    **status,
                    "ready": False,
                    "timeout": True,
                }

            await asyncio.sleep(interval)
