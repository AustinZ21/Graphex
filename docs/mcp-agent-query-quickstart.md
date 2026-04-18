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

This mode preserves original `line` mapping from previous output and replaces prior failed entries with fresh retry results.

Fail-control options:
- `--fail-fast`: stop at first failure.
- `--max-errors N`: stop when failure count reaches `N` (`0` means disabled).
- `--resume-from-output`: load existing output JSONL and skip previously processed `line` entries.
- `--only-failed-from-output`: extract failed items (ok==false) from output JSONL, reconstruct input, and retry only those queries (merges old successes with new retry results).

Output format:
- JSONL, one result per input line.
- Includes `ok`, `tool`, `arguments`, `attempts`, and either `result` or `error`.
- CLI summary includes `qps`, `retries`, `failed`, `cancelled`, `resumed_skipped`, `executed_now`, and `duration_sec` for quick throughput checks.

## 4.2) Run CG-first query strategy client (agent default route)

This script implements a default strategy for agents:
1. Query ContextGraph MCP first (`retrieve_context` + `find_call_graph`).
2. Keep graph context under a token budget.
3. Fallback to local code snippets only when graph hits are insufficient.

Run:

```powershell
python src/scripts/mcp_query_strategy.py --query "how indexing pipeline works" --base-url http://127.0.0.1:8011 --repo-root . --token-budget 1800 --graph-top-k 8 --min-graph-hits 3
```

Output fields:
- `strategy`: always `cg-first`
- `graph_context`: MCP graph hits with relations
- `quality_score`: aggregate graph context quality score
- `quality_threshold`: adaptive threshold used before fallback
- `used_fallback`: whether local snippet fallback was triggered
- `fallback_reason`: why fallback was triggered or skipped
- `fallback_context`: local snippets only when needed
- `estimated_tokens`: approximate token usage for returned context

## 6) Architecture analysis tools

These tools help agents understand project structure and dependencies:

- `get_architecture_overview()` - High-level stats (total files, symbols, languages, interconnectedness)
- `get_key_modules(limit)` - Find critical modules by importance (weighted by symbols + incoming calls)
- `get_file_stats(file_path)` - Detailed file metrics (symbols, incoming calls, outgoing calls)
- `analyze_dependencies(limit)` - Top file-to-file dependencies
- `find_dependency_chain(source_path, target_path)` - Analyze how files are connected through calls

Usage example:
```python
# Agent wants to understand codebase structure
overview = cg.get_architecture_overview()
key_files = cg.get_key_modules(limit=5)
dependencies = cg.analyze_dependencies(limit=10)
```

These tools enable agents to answer:
- "What is the core architecture of this project?"
- "Which modules are most central?"
- "How are these files related?"
- "What is the dependency flow?"

## 7) Import tracking & dependency analysis

These tools expose file-level import relationships:

- `get_file_imports(file_path)` - What files does this file import?
- `get_file_dependents(file_path)` - What files import this file?
- `get_dependency_overview(limit)` - Full import graph (file-to-file edges)
- `analyze_import_surface(limit)` - Files ranked by import connectivity

Usage example:
```python
# Agent wants to understand external dependencies
core_imports = cg.get_file_imports("src/core.py")
core_dependents = cg.get_file_dependents("src/core.py")
all_imports = cg.get_dependency_overview(limit=30)
```

Import tracking supports:
- Local relative imports (`./utils`, `../core`)
- Directory imports with index/init files
- Language-agnostic path resolution
- Multi-language: Python, TypeScript/JavaScript, Go, Rust, Java

## Symbol-level incremental indexing

Version 1.14.0 introduces fine-grained incremental updates:
- **Content hash**: detects any file change
- **Symbol hash**: detects changes to function/class signatures
- **Call hash**: detects changes to function call patterns
- **Import hash**: detects changes to import dependencies
- **Variable-flow hash**: detects assignment and return data-flow changes

## Variable flow tracking (v1.18.0)

ContextGraph now tracks lightweight intra-function data flow for Python and TypeScript/JavaScript.

Available tools:

- `find_variable(name, limit)` - Find variables by name or qualified name fragment
- `get_variable_flows(scope_qname, limit)` - Inspect assignment/return flows inside a function or method
- `trace_variable_lineage(qualified_name)` - Get one-hop upstream/downstream lineage for a variable

Usage example:

```python
# Agent wants to understand how data moves through a function
variables = cg.find_variable("result", limit=10)
flows = cg.get_variable_flows("backend.service.render", limit=20)
lineage = cg.trace_variable_lineage("backend.service.render:label")
```

What gets indexed:

- **Parameters**: function inputs are modeled as variable nodes
- **Assignments**: `x = y` becomes `y -> x`
- **Returns**: `return x` becomes `x -> __return__`
- **Roles**: variables are tagged as `parameter`, `local`, or `return`

This enables agents to answer:

- "Where does this returned value come from?"
- "Which input parameter influences this local variable?"
- "What intermediate variables exist inside this function?"

## Call-graph analysis and metrics (v1.17.0)

ContextGraph provides sophisticated call-graph analysis for understanding codebase architecture:

### Cycle Detection

```python
# Detect circular dependencies (A → B → C → A)
cycles = cg.detect_cycles()
# Returns: List of cyclic symbols
```

### Fan-in/Fan-out Analysis

```python
# How many symbols call this symbol? (dependencies)
fan_in = cg.compute_symbol_fan_in("myapp.core.process")
# Returns: ["caller1", "caller2", "caller3"]

# How many symbols does this symbol call? (dependencies it creates)
fan_out = cg.compute_symbol_fan_out("myapp.core.process")
# Returns: ["util.log", "util.cache", "db.query"]
```

### Critical Function Ranking

```python
# Find most important functions (high fan-in + central)
critical = cg.find_critical_functions(top_n=15)
# Returns: [(qualified_name, symbol_type, fan_in, fan_out, importance_score), ...]
```

Score = (fan_in * 0.6) + (normalized_fan_out * 0.4)

### Use Cases for Agents

- **Risk assessment**: Find cyclic dependencies that create maintenance risk
- **API design**: Identify functions with high fan-in (stable interfaces)
- **Refactoring**: Locate high-coupling points that are hard to change
- **Call-path optimization**: Understand call depths and potential bottlenecks

## Multi-language support (v1.16.0)

ContextGraph now supports **Go**, **Rust**, and **Java** in addition to Python and TypeScript/JavaScript:

```python
# Supported file extensions
SUPPORTED_EXTENSIONS = {
    ".py",              # Python
    ".ts", ".tsx",      # TypeScript
    ".js", ".jsx",      # JavaScript
    ".go",              # Go
    ".rs",              # Rust
    ".java",            # Java
}
```

Each parser uses regex-based lightweight extraction (no external dependencies):
- **Go**: Functions, structs, interfaces, methods, imports (packages)
- **Rust**: Modules, structs, traits, impl blocks, functions, imports (use)
- **Java**: Classes, interfaces, enums, methods, imports (packages)

**Enables agents to query codebases across 6 programming languages**, reducing token overhead by reusing global architecture queries instead of file reads.

## Performance benchmarking (v1.15.0)

ContextGraph includes a comprehensive performance testing framework:

```powershell
python -m src.scripts.run_benchmark --repo /path/to/project --output report.json
```

Measures:
- **Throughput**: files/sec, symbols/sec, calls/sec, imports/sec
- **Latency**: total indexing duration
- **Granularity**: per-tool and aggregate statistics

Example output:
```
=== ContextGraph Performance Benchmark ===

Repository: /path/to/project
Files indexed: 1250
Total symbols: 8945
Total calls: 42123
Total imports: 3421
Duration: 3245.67 ms
Throughput: 385.16 files/sec
Symbol indexing: 2754.92 symbols/sec
Call indexing: 12979.41 calls/sec
Import indexing: 1054.23 imports/sec

Report saved to: benchmark_report.json
```

The framework enables:
- Baseline measurements on any project
- Comparative analysis before/after optimization
- Capacity planning for large monorepos
- Performance regression detection

Benefit: Small edits (comments, whitespace, method bodies) won't retrigger expensive symbol/call/import updates.

Example performance gain: editing method body in a 200-function file only re-indexes that one method, not the entire file's symbol table.

Read/query tools:
- `find_symbol`
- `find_callers`
- `find_callees`
- `retrieve_context`
- `find_call_graph`
- `strategy_query`
- `get_stats`
- `run_eval`
- `clear_cache`
- `get_index_job_status`
- `wait_for_index_ready`

`strategy_query` is the server-side default agent route. It executes the CG-first policy inside the MCP server itself: graph retrieval first, bounded token budget, local snippet fallback only when graph hits are insufficient.

Fallback is no longer based only on fixed hit count. The strategy also evaluates graph context quality using query match, snippet presence, and relation richness before deciding to fallback.

`retrieve_context` now returns enriched items with:
- `summary`: compact symbol/location summary
- `snippet`: bounded code snippet around the symbol
- `callers` / `callees`: compact relation summaries inline
- `callers_count` / `callees_count`: inline relation counts

This reduces the need for agents to perform extra file reads after initial graph retrieval.

When these inline relations are present, `strategy_query` can often skip a separate `find_call_graph` call for the same symbol.

Indexing tools (queued):
- `index_full`
- `index_incremental`

Current language indexing support:
- Python: symbols, imports, call edges (via AST)
- TypeScript/JavaScript: symbols, imports, call edges (via regex)

For TS/JS projects, ContextGraph now indexes:
- Top-level classes, functions, interfaces, types, enums
- Basic class methods
- Function/method calls for relationship mapping

This enables repository-wide lookup, relationship discovery, and CG-first agent routing across both Python and TS/JS codebases.

Index status workflow:
1. Call `index_full` or `index_incremental` and keep returned `job_id`.
2. Call `get_index_job_status(job_id)` for polling status.
3. Or call `wait_for_index_ready(job_id, timeout_sec, poll_interval_sec)` to block until `done`/`failed`.

## Troubleshooting

- `400 Bad Request` on `/mcp/messages`: session id is missing or expired. Re-open `/mcp/sse` and use the fresh endpoint payload.
- `404` on MCP path: verify base URL and port, then query `/mcp` first.
- Port conflict on `8000`: use another port (`8011` in examples).
