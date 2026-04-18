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

import redis.asyncio as aioredis
import structlog

from backend.queue.models import IndexJob

log = structlog.get_logger()

STREAM_KEY = "contextgraph:jobs"
CONSUMER_GROUP = "indexer-group"
CONSUMER_NAME = "indexer-worker"


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
        log.info("mq.published", job_id=job.job_id, type=job.job_type, stream_id=stream_id)
        return stream_id


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

    async def _ensure_group(self) -> None:
        try:
            await self._client.xgroup_create(  # type: ignore[union-attr]
                STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
