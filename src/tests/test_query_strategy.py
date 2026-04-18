from pathlib import Path

from backend.agent.query_strategy import (
    estimate_tokens,
    trim_items_to_budget,
    read_code_snippet,
    run_cg_first_strategy,
)


def test_estimate_tokens_empty_and_non_empty():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcdefgh") == 2


def test_trim_items_to_budget_keeps_order_and_budget():
    items = [
        {"name": "a", "payload": "x" * 20},
        {"name": "b", "payload": "y" * 200},
        {"name": "c", "payload": "z" * 20},
    ]
    kept, used = trim_items_to_budget(items, budget_tokens=40)
    assert len(kept) >= 1
    assert used <= 40
    assert kept[0]["name"] == "a"


def test_read_code_snippet_respects_bounds(tmp_path: Path):
    content = "\n".join(
        [
            "line1",
            "line2",
            "line3",
            "line4",
            "line5",
            "line6",
        ]
    )
    file_path = tmp_path / "sample.py"
    file_path.write_text(content, encoding="utf-8")

    snippet = read_code_snippet(
        repo_root=tmp_path,
        relative_path="sample.py",
        line_start=3,
        line_end=4,
        context_lines=1,
        max_chars=200,
    )

    assert "line2" in snippet
    assert "line3" in snippet
    assert "line4" in snippet
    assert "line5" in snippet


def test_run_cg_first_strategy_without_fallback(tmp_path: Path):
    def retrieve_graph_hits(query: str, limit: int):
        return [
            {
                "qualified_name": "pkg.mod.fn",
                "symbol_type": "function",
                "file_path": "sample.py",
                "line_start": 1,
                "line_end": 3,
            }
        ]

    def get_call_graph(qualified_name: str, depth: int):
        return {"callers": ["caller.a"], "callees": ["callee.b"]}

    result = run_cg_first_strategy(
        query="sample",
        repo_root=tmp_path,
        retrieve_graph_hits=retrieve_graph_hits,
        get_call_graph=get_call_graph,
        graph_top_k=5,
        min_graph_hits=1,
        token_budget=500,
    )

    assert result["strategy"] == "cg-first"
    assert result["used_fallback"] is False
    assert len(result["graph_context"]) == 1
