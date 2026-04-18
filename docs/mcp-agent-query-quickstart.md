# ContextGraph MCP Query Quickstart

This quickstart shows how an agent can query graph results through the ContextGraph MCP server.

## 1) Start dependencies

```powershell
docker compose --profile dev up -d
```

Expected dev containers:
- `contextgraph-falkordb-dev` on `localhost:16379`
- `contextgraph-redis-dev` on `localhost:6380`

## 2) Start ContextGraph backend

```powershell
$env:PYTHONPATH='src'
$env:FALKORDB_HOST='localhost'
$env:FALKORDB_PORT='16379'
$env:QUEUE_REDIS_URL='redis://localhost:6380/1'
$env:CACHE_REDIS_URL='redis://localhost:6380'
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8011
```

## 3) Discover MCP endpoints

```powershell
Invoke-RestMethod http://127.0.0.1:8011/mcp | ConvertTo-Json
```

Current transport:
- `GET /mcp/sse`
- `POST /mcp/messages` (session-aware endpoint discovered from SSE payload)

## 4) Run minimal query client

```powershell
python src/scripts/mcp_query_example.py --base-url http://127.0.0.1:8011 --name IndexPipeline --limit 5
```

The script:
1. Opens SSE stream at `/mcp/sse`.
2. Reads first endpoint payload (with session context).
3. Sends `tools/call` for `find_symbol`.

## 5) Available graph query tools

Read/query tools:
- `find_symbol`
- `find_callers`
- `find_callees`
- `retrieve_context`
- `find_call_graph`
- `get_stats`
- `run_eval`
- `clear_cache`

Indexing tools (queued):
- `index_full`
- `index_incremental`

## Troubleshooting

- `400 Bad Request` on `/mcp/messages`: session id is missing or expired. Re-open `/mcp/sse` and use the fresh endpoint payload.
- `404` on MCP path: verify base URL and port, then query `/mcp` first.
- Port conflict on `8000`: use another port (`8011` in examples).
