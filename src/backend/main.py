"""ContextGraph application entry point.

Startup sequence
----------------
1. Connect to FalkorDB and ensure graph indexes.
2. Connect MCP producer to Redis Stream (client-side MQ).
3. Initialize Redis query cache (Phase 3).
4. Initialize trace recorder + evaluator (Phase 3).
5. Initialize MCP tool registry with live graph + producer + cache + recorder.
6. Launch indexer consumer loop (server-side MQ) as background task.
7. Launch trace evaluator background coroutine.

Shutdown sequence reverses the above gracefully.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.auth.database import init_db
from backend.auth.middleware import ProjectTokenMiddleware
from backend.auth.router import router as auth_router
from backend.graph.client import GraphClient
from backend.indexer.consumer import IndexerConsumer
from backend.tools.producer import MCPProducer
from backend.tools import server as mcp_server

log = structlog.get_logger()

FALKORDB_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.getenv("FALKORDB_PORT", "6379"))
QUEUE_REDIS_URL = os.getenv("QUEUE_REDIS_URL", "redis://localhost:6380/1")
CACHE_REDIS_URL = os.getenv("CACHE_REDIS_URL", "redis://localhost:6380")  # db=2 set in QueryCache
TRACE_ENABLED = os.getenv("TRACE_ENABLED", "true").lower() == "true"

_graph = GraphClient(host=FALKORDB_HOST, port=FALKORDB_PORT)
_producer = MCPProducer(redis_url=QUEUE_REDIS_URL)
_consumer: IndexerConsumer | None = None
_consumer_task: asyncio.Task | None = None
_trace_evaluator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _consumer, _consumer_task, _trace_evaluator

    # Startup: auth DB
    await init_db()

    _graph.connect()
    _graph.ensure_indexes()
    await _producer.connect()

    # Phase 3: query cache
    cache = None
    recorder = None
    try:
        from backend.cache.query_cache import QueryCache
        cache = QueryCache(redis_url=CACHE_REDIS_URL)
        log.info("cache.connected")
    except Exception as exc:
        log.warning("cache.disabled", reason=str(exc))

    # Phase 3: trace recorder + evaluator
    if TRACE_ENABLED:
        try:
            from backend.eval.trace_eval import TraceRecorder, TraceEvaluator
            recorder = TraceRecorder(redis_url=CACHE_REDIS_URL)
            _trace_evaluator = TraceEvaluator(redis_url=CACHE_REDIS_URL, graph_client=_graph)
            await _trace_evaluator.start()
        except Exception as exc:
            log.warning("trace_eval.disabled", reason=str(exc))

    mcp_server.init(graph=_graph, producer=_producer, cache=cache, recorder=recorder)
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
    if _trace_evaluator:
        await _trace_evaluator.stop()
    if recorder:
        recorder.close()
    if cache:
        cache.close()
    await _producer.close()
    _graph.close()
    log.info("contextgraph.stopped")


app = FastAPI(title="ContextGraph", version="0.2.2", lifespan=lifespan)

# ── Auth middleware (validates Bearer token on /mcp routes) ────────────────
app.add_middleware(ProjectTokenMiddleware)

# ── Auth API ───────────────────────────────────────────────────────────────
app.include_router(auth_router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "contextgraph"}


@app.get("/mcp")
async def mcp_info() -> dict:
    return {
        "transport": "sse",
        "sse_endpoint": "/mcp/sse",
        "message_endpoint": "/mcp/messages",
        "auth": {
            "type": "Bearer",
            "required_headers": ["Authorization", "X-Project-ID"],
            "notes": "Bearer token must be an active mcp token bound to the provided project_id",
        },
    }


# ── MCP SSE transport ──────────────────────────────────────────────────────
app.mount("/mcp", mcp_server.mcp.sse_app(mount_path="/mcp"))

# ── Admin SPA (served last so API routes take precedence) ─────────────────
_FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


@app.get("/admin", include_in_schema=False)
async def admin_ui():
    return FileResponse(_FRONTEND / "index.html")


if _FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")


if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)


