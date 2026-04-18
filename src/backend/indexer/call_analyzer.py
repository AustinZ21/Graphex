"""Call-graph edge extractor using stdlib ast.

For every function/method in a parsed file, walks the AST to find all
direct function/method call sites and returns (caller_qname, callee_name)
pairs.  These are later resolved to qualified names in the pipeline and
written as CALLS edges in FalkorDB.

Resolution strategy (best-effort, no type inference):
- Simple name calls  e.g. `helper()` → matched against symbols in same file.
- Attribute calls    e.g. `self.run()` or `obj.run()` → matched by method name
  across all indexed symbols.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass
class RawCall:
    caller_qname: str
    callee_name: str     # simple name; resolution happens in pipeline


class CallAnalyzer:
    """Extract CALLS relationships from a Python file's AST."""

    def extract(
        self,
        tree: ast.AST,
        file_path: str,
        module_qname: str,
    ) -> list[RawCall]:
        calls: list[RawCall] = []
        self._visit_body(
            list(ast.walk(tree)),
            tree,
            module_qname,
            calls,
        )
        return calls

    # ------------------------------------------------------------------
    def _visit_body(
        self,
        all_nodes: list,
        tree: ast.AST,
        module_qname: str,
        out: list[RawCall],
    ) -> None:
        for node in all_nodes:
            if isinstance(node, ast.ClassDef):
                class_qname = f"{module_qname}.{node.name}"
                for item in ast.walk(node):
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func_qname = f"{class_qname}.{item.name}"
                        self._collect_calls(item, func_qname, out)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parent = self._parent(tree, node)
                if isinstance(parent, ast.ClassDef):
                    continue  # handled above
                func_qname = f"{module_qname}.{node.name}"
                self._collect_calls(node, func_qname, out)

    def _collect_calls(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        caller_qname: str,
        out: list[RawCall],
    ) -> None:
        for node in ast.walk(func_node):
            if not isinstance(node, ast.Call):
                continue
            name = self._extract_call_name(node)
            if name:
                out.append(RawCall(caller_qname=caller_qname, callee_name=name))

    @staticmethod
    def _extract_call_name(call: ast.Call) -> str | None:
        if isinstance(call.func, ast.Name):
            return call.func.id
        if isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None

    @staticmethod
    def _parent(tree: ast.AST, target: ast.AST) -> ast.AST | None:
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                if child is target:
                    return node
        return None
