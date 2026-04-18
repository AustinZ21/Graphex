"""Cypher MERGE/MATCH templates for the ContextGraph schema.

Node labels   : Repository, File, Symbol
Edge types    : CONTAINS, DEFINES, IMPORTS, CALLS, REFERENCES

All write queries use MERGE to guarantee idempotency on re-index.
"""

# ---------------------------------------------------------------------------
# Node MERGE
# ---------------------------------------------------------------------------

MERGE_REPO = """
MERGE (r:Repository {path: $path})
SET r.name = $name
"""

MERGE_FILE = """
MERGE (f:File {path: $path})
SET f.language = $language,
    f.content_hash = $content_hash
"""

MERGE_SYMBOL = """
MERGE (s:Symbol {qualified_name: $qualified_name})
SET s.name           = $name,
    s.symbol_type    = $symbol_type,
    s.file_path      = $file_path,
    s.line_start     = $line_start,
    s.line_end       = $line_end
"""

# ---------------------------------------------------------------------------
# Edge MERGE
# ---------------------------------------------------------------------------

EDGE_REPO_CONTAINS_FILE = """
MATCH (r:Repository {path: $repo_path})
MATCH (f:File {path: $file_path})
MERGE (r)-[:CONTAINS]->(f)
"""

EDGE_FILE_DEFINES_SYMBOL = """
MATCH (f:File {path: $file_path})
MATCH (s:Symbol {qualified_name: $qualified_name})
MERGE (f)-[:DEFINES]->(s)
"""

EDGE_FILE_IMPORTS = """
MATCH (src:File {path: $src_path})
MATCH (tgt:File {path: $target_path})
MERGE (src)-[:IMPORTS]->(tgt)
"""

EDGE_SYMBOL_CALLS = """
MATCH (caller:Symbol {qualified_name: $caller_qname})
MATCH (callee:Symbol {qualified_name: $callee_qname})
MERGE (caller)-[:CALLS]->(callee)
"""

QUERY_FILE_HASH = """
MATCH (f:File {path: $path})
RETURN f.content_hash AS hash
"""

# ---------------------------------------------------------------------------
# Retrieval queries
# ---------------------------------------------------------------------------

QUERY_FIND_SYMBOL = """
MATCH (s:Symbol)
WHERE s.name = $name OR s.qualified_name CONTAINS $name
RETURN s.qualified_name, s.symbol_type, s.file_path, s.line_start, s.line_end
ORDER BY s.qualified_name
LIMIT $limit
"""

QUERY_FIND_CALLERS = """
MATCH (caller:Symbol)-[:CALLS]->(callee:Symbol {qualified_name: $qualified_name})
RETURN caller.qualified_name, caller.file_path, caller.line_start
LIMIT $limit
"""

QUERY_FIND_CALLEES = """
MATCH (caller:Symbol {qualified_name: $qualified_name})-[:CALLS]->(callee:Symbol)
RETURN callee.qualified_name, callee.file_path, callee.line_start
LIMIT $limit
"""

QUERY_RETRIEVE_CONTEXT = """
MATCH (s:Symbol)
WHERE s.name CONTAINS $query OR s.qualified_name CONTAINS $query
MATCH (f:File {path: s.file_path})
RETURN s.qualified_name, s.symbol_type, s.file_path, s.line_start, s.line_end
ORDER BY s.name
LIMIT $limit
"""

QUERY_COUNT_SYMBOLS = """
MATCH (s:Symbol) RETURN count(s) AS cnt
"""

# ---------------------------------------------------------------------------
# Aggregation queries (architecture analysis)
# ---------------------------------------------------------------------------

QUERY_FILE_STATS = """
MATCH (f:File {path: $file_path})
WITH f
OPTIONAL MATCH (f)-[:DEFINES]->(s:Symbol)
WITH f, count(s) AS symbol_count
OPTIONAL MATCH (f)<-[:CALLS]-(caller:Symbol)
WITH f, symbol_count, count(DISTINCT caller) AS incoming_calls
OPTIONAL MATCH (f)-[:DEFINES]-(s:Symbol)-[:CALLS]->()
RETURN symbol_count AS symbols, incoming_calls, count(DISTINCT s) AS symbols_with_outgoing_calls
"""

QUERY_KEY_FILES = """
MATCH (f:File)
WITH f
OPTIONAL MATCH (f)-[:DEFINES]->(s:Symbol)
WITH f, count(s) AS symbol_count
OPTIONAL MATCH (f)<-[:CALLS]-(caller:Symbol)
WITH f, symbol_count, count(DISTINCT caller) AS incoming_calls
OPTIONAL MATCH (f)-[:DEFINES]-(s:Symbol)-[:CALLS]->()
WITH f, symbol_count, incoming_calls, count(DISTINCT s) AS symbols_with_calls,
     (symbol_count * 0.3 + coalesce(incoming_calls, 0) * 0.7) AS importance_score
ORDER BY importance_score DESC
LIMIT $limit
RETURN f.path AS file_path, f.language AS language, symbol_count, incoming_calls, symbols_with_calls, importance_score
"""

QUERY_MODULE_DEPENDENCIES = """
MATCH (f1:File)-[:DEFINES]->(s1:Symbol)-[:CALLS]->(s2:Symbol)<-[:DEFINES]-(f2:File)
WHERE f1.path <> f2.path
WITH f1.path AS from_file, f2.path AS to_file, count(DISTINCT s1) AS caller_symbols, count(DISTINCT s2) AS callee_symbols
RETURN from_file, to_file, caller_symbols, callee_symbols
ORDER BY caller_symbols DESC
LIMIT $limit
"""

QUERY_ARCHITECTURE_OVERVIEW = """
MATCH (f:File)
WITH f
OPTIONAL MATCH (f)-[:DEFINES]->(s:Symbol)
WITH f, count(s) AS symbol_count
OPTIONAL MATCH (f)<-[:CALLS]-(caller:Symbol)
WITH f, symbol_count, count(DISTINCT caller) AS callers
OPTIONAL MATCH (f)-[:DEFINES]-(s:Symbol)-[:CALLS]->()
WITH f, symbol_count, callers, count(s) AS functions_with_calls
OPTIONAL MATCH (f)<-[:DEFINES]-(s:Symbol)<-[:CALLS]-()
RETURN 
  count(DISTINCT f) AS total_files,
  sum(symbol_count) AS total_symbols,
  count(DISTINCT f.language) AS languages,
  sum(CASE WHEN callers > 0 THEN 1 ELSE 0 END) AS files_with_incoming_calls,
  avg(symbol_count) AS avg_symbols_per_file,
  avg(callers) AS avg_callers_per_file
"""

QUERY_FILE_DEPENDENCY_CHAIN = """
MATCH path = (f1:File)-[:DEFINES]->(s1:Symbol)-[:CALLS*1..3]->(s2:Symbol)<-[:DEFINES]-(f2:File)
WHERE f1.path = $source_path AND f2.path = $target_path
WITH relationships(path) AS edges
RETURN length(edges) AS hops, count(*) AS paths
ORDER BY hops
LIMIT 10
"""
