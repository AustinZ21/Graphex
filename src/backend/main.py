"""ContextGraph application entry point.

Startup sequence
----------------
1. Connect to FalkorDB and ensure graph indexes.
2. Connect MCP producer to Redis Stream (client-side MQ).
3. Initialize MCP tool registry with live graph + producer.
4. Launch indexer consumer loop (server-side MQ) as background task.

Shutdown sequence reverses the above gracefully.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI

from backend.graph.client import GraphClient
from backend.indexer.consumer import IndexerConsumer
from backend.tools.producer import MCPProducer
from backend.tools import server as mcp_server

log = structlog.get_logger()

FALKORDB_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.getenv("FALKORDB_PORT", "6379"))
QUEUE_REDIS_URL = os.getenv("QUEUE_REDIS_URL", "redis://localhost:6380/1")

_graph = GraphClient(host=FALKORDB_HOST, port=FALKORDB_PORT)
_producer = MCPProducer(redis_url=QUEUE_REDIS_URL)
_consumer: IndexerConsumer | None = None
_consumer_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer, _consumer_task

    # Startup
    _graph.connect()
    _graph.ensure_indexes()
    await _producer.connect()
    mcp_server.init(graph=_graph, producer=_producer)
    _consumer = IndexerConsumer(redis_url=QUEUE_REDIS_URL, graph=_graph)
    _consumer_task = asyncio.create_task(_consumer.start())
    log.info("contextgraph.started", falkordb=f"{FALKORDB_HOST}:{FALKORDB_PORT}")

    yield

    # Shutdown
    if _consumer:
        await _consumer.stop()
    if _consumer_task:
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    await _producer.close()
    _graph.close()
    log.info("contextgraph.stopped")


app = FastAPI(title="ContextGraph", version="0.1.0", lifespan=lifespan)

# Mount MCP server at /mcp (Streamable HTTP transport)
app.mount("/mcp", mcp_server.mcp.streamable_http_app())


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "contextgraph"}


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)

