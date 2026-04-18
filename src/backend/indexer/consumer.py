"""Indexer consumer – reads jobs from the Redis Stream and drives the pipeline.

Runs as a long-lived async loop inside the FastAPI lifespan.
Uses consumer group semantics:
- At-least-once delivery: ACK only after successful pipeline run.
- Exponential backoff on transient errors to avoid tight retry storms.
"""

from __future__ import annotations

import asyncio
import structlog

from backend.queue.streams import JobConsumer
from backend.queue.models import JobType, IndexJob
from backend.graph.client import GraphClient
from backend.indexer.pipeline import IndexPipeline

log = structlog.get_logger()

_BASE_SLEEP = 1.0
_MAX_SLEEP = 30.0


class IndexerConsumer:
    def __init__(self, redis_url: str, graph: GraphClient) -> None:
        self._consumer = JobConsumer(redis_url=redis_url)
        self._pipeline = IndexPipeline(graph=graph)
        self._running = False
        self._sleep = _BASE_SLEEP

    async def start(self) -> None:
        await self._consumer.connect()
        self._running = True
        log.info("indexer.consumer.started")
        while self._running:
            try:
                jobs = await self._consumer.consume(count=1, block_ms=3_000)
                for msg_id, job in jobs:
                    await self._process(msg_id, job)
                self._sleep = _BASE_SLEEP  # reset backoff on success
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("indexer.consumer.loop_error", error=str(exc))
                await asyncio.sleep(self._sleep)
                self._sleep = min(self._sleep * 2, _MAX_SLEEP)

    async def stop(self) -> None:
        self._running = False
        await self._consumer.close()
        log.info("indexer.consumer.stopped")

    async def _process(self, msg_id: str, job: IndexJob) -> None:
        log.info("indexer.job.start", job_id=job.job_id, type=job.job_type)
        try:
            await self._consumer.set_job_processing(job)
            if job.job_type == JobType.INDEX_FULL:
                stats = await asyncio.to_thread(
                    self._pipeline.index_full, job.repo_path
                )
            elif job.job_type == JobType.INDEX_INCREMENTAL:
                stats = await asyncio.to_thread(
                    self._pipeline.index_incremental,
                    job.repo_path,
                    job.changed_paths or [],
                )
            else:
                log.warning("indexer.job.unknown_type", type=job.job_type)
                stats = {}
            await self._consumer.ack(msg_id)
            await self._consumer.set_job_done(job, stats)
            log.info("indexer.job.done", job_id=job.job_id, **stats)
        except Exception as exc:
            await self._consumer.set_job_failed(job, str(exc))
            log.error("indexer.job.failed", job_id=job.job_id, error=str(exc))
            # Do NOT ack – message stays in PEL for manual inspection / retry
