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
