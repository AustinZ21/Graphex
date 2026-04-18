"""MCP-side job producer.

MCP tool handlers call this to enqueue indexing jobs into the Redis Stream.
Decouples tool response time from actual indexing work.
"""

from __future__ import annotations

from backend.queue.streams import JobProducer
from backend.queue.models import IndexJob, JobType


class MCPProducer:
    def __init__(self, redis_url: str) -> None:
        self._producer = JobProducer(redis_url=redis_url)

    async def connect(self) -> None:
        await self._producer.connect()

    async def close(self) -> None:
        await self._producer.close()

    async def submit_full_index(self, repo_path: str) -> str:
        job = IndexJob(job_type=JobType.INDEX_FULL, repo_path=repo_path)
        return await self._producer.publish(job)

    async def submit_incremental_index(
        self, repo_path: str, changed_paths: list[str]
    ) -> str:
        job = IndexJob(
            job_type=JobType.INDEX_INCREMENTAL,
            repo_path=repo_path,
            changed_paths=changed_paths,
        )
        return await self._producer.publish(job)
