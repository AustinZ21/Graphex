"""CG-first agent query strategy demo client.

Usage:
    set CONTEXTGRAPH_MCP_TOKEN=<project-token>
    set CONTEXTGRAPH_PROJECT_ID=<project-id>
  python src/scripts/mcp_query_strategy.py \
    --query "index pipeline" \
    --base-url http://127.0.0.1:8011 \
    --repo-root . \
    --token-budget 1800
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from backend.agent.query_strategy import CGFirstQueryStrategy, StrategyConfig


def main() -> int:
    parser = argparse.ArgumentParser(description="CG-first query strategy client")
    parser.add_argument("--query", required=True, help="Question or intent from agent")
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--repo-root", default=".", help="Repository root for local fallback snippets")
    parser.add_argument("--graph-top-k", type=int, default=8)
    parser.add_argument("--min-graph-hits", type=int, default=3)
    parser.add_argument("--token-budget", type=int, default=1800)
    parser.add_argument("--relation-depth", type=int, default=1)
    parser.add_argument("--fallback-max-files", type=int, default=3)
    parser.add_argument("--token", default=os.getenv("CONTEXTGRAPH_MCP_TOKEN"))
    parser.add_argument("--project-id", default=os.getenv("CONTEXTGRAPH_PROJECT_ID"))
    args = parser.parse_args()

    cfg = StrategyConfig(
        base_url=args.base_url,
        repo_root=Path(args.repo_root).resolve(),
        graph_top_k=max(1, args.graph_top_k),
        min_graph_hits=max(1, args.min_graph_hits),
        token_budget=max(200, args.token_budget),
        relation_depth=max(1, args.relation_depth),
        fallback_max_files=max(1, args.fallback_max_files),
        mcp_token=args.token,
        project_id=args.project_id,
    )
    strategy = CGFirstQueryStrategy(cfg)
    result = strategy.run(args.query)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
