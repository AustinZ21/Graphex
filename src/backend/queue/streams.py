"""Redis Streams-backed message queue for reliable job delivery.

Architecture
------------
- Producer  : MCP tool handlers publish IndexJob messages to the stream.
- Consumer  : Indexer worker reads via consumer group (at-least-once delivery).
- ACK       : Only after successful processing to guarantee no job is silently lost.

Stream key  : contextgraph:jobs
Group name  : indexer-group
Consumer ID : indexer-worker-{instance}
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog

from backend.queue.models import IndexJob

log = structlog.get_logger()

STREAM_KEY = "contextgraph:jobs"
CONSUMER_GROUP = "indexer-group"
CONSUMER_NAME = "indexer-worker"
STATUS_KEY_PREFIX = "contextgraph:job:status:"
STATUS_TTL_SEC = 7 * 24 * 60 * 60


def _status_key(job_id: str) -> str:
    return f"{STATUS_KEY_PREFIX}{job_id}"


async def _set_job_status(
    client: aioredis.Redis,
    job: IndexJob,
    status: str,
    stream_id: str | None = None,
    error: str | None = None,
    extra: dict | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "job_id": job.job_id,
        "job_type": job.job_type.value,
        "repo_path": job.repo_path,
        "status": status,
        "created_at": job.created_at,
        "updated_at": now,
    }
    if stream_id is not None:
        payload["stream_id"] = stream_id
    if error is not None:
        payload["error"] = error
    if extra:
        for k, v in extra.items():
            payload[k] = str(v)

    key = _status_key(job.job_id)
    await client.hset(key, mapping=payload)
    await client.expire(key, STATUS_TTL_SEC)


async def _get_job_status(client: aioredis.Redis, job_id: str) -> dict | None:
    key = _status_key(job_id)
    data = await client.hgetall(key)
    if not data:
        return None
    return dict(data)


class JobProducer:
    """Publishes IndexJob messages to the Redis Stream."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            self._redis_url, decode_responses=True, socket_connect_timeout=5
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def publish(self, job: IndexJob) -> str:
        if not self._client:
            raise RuntimeError("JobProducer not connected")
        stream_id: str = await self._client.xadd(
            STREAM_KEY,
            {"payload": job.model_dump_json()},
            maxlen=10_000,
            approximate=True,
        )
        await _set_job_status(
            self._client,
            job,
            status="pending",
            stream_id=stream_id,
        )
        log.info("mq.published", job_id=job.job_id, type=job.job_type, stream_id=stream_id)
        return stream_id

    async def get_job_status(self, job_id: str) -> dict | None:
        if not self._client:
            raise RuntimeError("JobProducer not connected")
        return await _get_job_status(self._client, job_id)


class JobConsumer:
    """Reads IndexJob messages from the Redis Stream via consumer group."""

    def __init__(self, redis_url: str, consumer_name: str = CONSUMER_NAME) -> None:
        self._redis_url = redis_url
        self._consumer_name = consumer_name
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.from_url(
            self._redis_url, decode_responses=True, socket_connect_timeout=5
        )
        await self._ensure_group()

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def consume(
        self, count: int = 1, block_ms: int = 3_000
    ) -> list[tuple[str, IndexJob]]:
        """Return up to *count* jobs, blocking at most *block_ms* ms."""
        if not self._client:
            raise RuntimeError("JobConsumer not connected")
        results = await self._client.xreadgroup(
            CONSUMER_GROUP,
            self._consumer_name,
            {STREAM_KEY: ">"},
            count=count,
            block=block_ms,
        )
        jobs: list[tuple[str, IndexJob]] = []
        if results:
            for _stream, messages in results:
                for msg_id, data in messages:
                    job = IndexJob.model_validate_json(data["payload"])
                    jobs.append((msg_id, job))
        return jobs

    async def ack(self, message_id: str) -> None:
        """Acknowledge successful processing to remove the message from PEL."""
        if not self._client:
            raise RuntimeError("JobConsumer not connected")
        await self._client.xack(STREAM_KEY, CONSUMER_GROUP, message_id)
        log.info("mq.acked", stream_id=message_id)

    async def set_job_processing(self, job: IndexJob) -> None:
        if not self._client:
            raise RuntimeError("JobConsumer not connected")
        await _set_job_status(self._client, job, status="processing")

    async def set_job_done(self, job: IndexJob, stats: dict) -> None:
        if not self._client:
            raise RuntimeError("JobConsumer not connected")
        await _set_job_status(self._client, job, status="done", extra=stats)

    async def set_job_failed(self, job: IndexJob, error: str) -> None:
        if not self._client:
            raise RuntimeError("JobConsumer not connected")
        await _set_job_status(self._client, job, status="failed", error=error)

    async def get_job_status(self, job_id: str) -> dict | None:
        """Get status of a specific job."""
        if not self._client:
            raise RuntimeError("JobConsumer not connected")
        return await _get_job_status(self._client, job_id)

    async def get_jobs_by_repo(self, repo_path: str) -> list[dict]:
        """Get all job statuses for a given repo path, most recent first.
        Matching is case-insensitive to handle Windows path variations.
        """
        if not self._client:
            raise RuntimeError("JobConsumer not connected")
        # Scan all job status keys and find those matching the repo_path (case-insensitive)
        jobs = []
        cursor = 0
        repo_path_lower = repo_path.lower()
        while True:
            cursor, keys = await self._client.scan(
                cursor,
                match=f"{STATUS_KEY_PREFIX}*",
                count=100
            )
            for key in keys:
                status_data = await self._client.hgetall(key)
                if status_data and status_data.get("repo_path", "").lower() == repo_path_lower:
                    jobs.append(dict(status_data))
            if cursor == 0:
                break
        # Sort by updated_at, most recent first
        jobs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return jobs

    async def _ensure_group(self) -> None:
        try:
            await self._client.xgroup_create(  # type: ignore[union-attr]
                STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
