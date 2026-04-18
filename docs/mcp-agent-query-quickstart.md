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

Node.js version:

```powershell
node src/scripts/mcp_query_example_node.mjs --base-url http://127.0.0.1:8011 --name IndexPipeline --limit 5
```

The script:
1. Opens SSE stream at `/mcp/sse`.
2. Reads first endpoint payload (with session context).
3. Sends `tools/call` for `find_symbol`.

## 4.1) Run batch query client (for evaluation loops)

Sample input file:
- `docs/mcp-query-batch.sample.jsonl`

Run:

```powershell
python src/scripts/mcp_query_batch.py --base-url http://127.0.0.1:8011 --input docs/mcp-query-batch.sample.jsonl --output docs/mcp-query-batch.result.jsonl --concurrency 8 --retries 2 --request-timeout-sec 20 --max-errors 5
```

Resume mode (skip already completed lines from existing output):

```powershell
python src/scripts/mcp_query_batch.py --base-url http://127.0.0.1:8011 --input docs/mcp-query-batch.sample.jsonl --output docs/mcp-query-batch.result.jsonl --resume-from-output
```

Retry-only-failed mode (extract failed items from output and retry only those):

```powershell
python src/scripts/mcp_query_batch.py --base-url http://127.0.0.1:8011 --input docs/mcp-query-batch.sample.jsonl --output docs/mcp-query-batch.result.jsonl --only-failed-from-output --retries 3
```

Fail-control options:
- `--fail-fast`: stop at first failure.
- `--max-errors N`: stop when failure count reaches `N` (`0` means disabled).
- `--resume-from-output`: load existing output JSONL and skip previously processed `line` entries.
- `--only-failed-from-output`: extract failed items (ok==false) from output JSONL, reconstruct input, and retry only those queries (merges old successes with new retry results).

Output format:
- JSONL, one result per input line.
- Includes `ok`, `tool`, `arguments`, `attempts`, and either `result` or `error`.
- CLI summary includes `qps`, `retries`, `failed`, `cancelled`, `resumed_skipped`, `executed_now`, and `duration_sec` for quick throughput checks.

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
