"""Call-graph analysis and metrics computation.

Provides high-level insights into codebase structure:
- Cycle detection (circular dependencies)
- Fan-in/fan-out computation (call counts)
- Critical path identification (longest call chains)
- Symbol importance ranking
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict, deque
from typing import DefaultDict


@dataclass
class CycleInfo:
    """Information about a detected cycle."""
    symbols: list[str]  # Qualified names forming cycle
    length: int  # Cycle length
    
    def __str__(self) -> str:
        return " -> ".join(self.symbols) + " -> " + self.symbols[0]


@dataclass
class SymbolMetrics:
    """Call-graph metrics for a single symbol."""
    qualified_name: str
    fan_in: int  # Number of distinct callers
    fan_out: int  # Number of distinct callees
    in_cycle: bool  # Is symbol part of any cycle
    cycles: list[CycleInfo]  # All cycles involving this symbol
    depth: int  # Maximum call depth from roots


@dataclass
class GraphMetrics:
    """Overall call-graph statistics."""
    total_symbols: int
    total_calls: int
    symbols_with_cycles: int
    total_cycles: int
    max_cycle_length: int
    avg_fan_in: float
    avg_fan_out: float
    max_fan_in: int
    max_fan_out: int
    max_call_depth: int


class CallGraphAnalyzer:
    """Analyze call-graph structure and compute metrics."""

    def __init__(self) -> None:
        self._graph: dict[str, set[str]] = {}  # qualified_name -> {callees}
        self._reverse_graph: dict[str, set[str]] = {}  # qualified_name -> {callers}
        self._all_symbols: set[str] = set()

    def build_from_calls(self, calls: list[tuple[str, str]]) -> None:
        """Build call graph from (caller, callee) pairs.
        
        Args:
            calls: List of (caller_qname, callee_qname) tuples
        """
        self._graph = defaultdict(set)
        self._reverse_graph = defaultdict(set)
        self._all_symbols = set()

        for caller, callee in calls:
            self._graph[caller].add(callee)
            self._reverse_graph[callee].add(caller)
            self._all_symbols.add(caller)
            self._all_symbols.add(callee)

        # Ensure all symbols are in graph (even if they don't call anything)
        for sym in self._all_symbols:
            if sym not in self._graph:
                self._graph[sym] = set()
            if sym not in self._reverse_graph:
                self._reverse_graph[sym] = set()

    def detect_cycles(self) -> list[CycleInfo]:
        """Detect all cycles in the call graph using DFS.
        
        Returns:
            List of CycleInfo objects representing cycles
        """
        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycles: list[CycleInfo] = []

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self._graph.get(node, set()):
                if neighbor not in visited:
                    dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Found cycle: extract from neighbor to current node
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(CycleInfo(symbols=cycle[:-1], length=len(cycle) - 1))

            path.pop()
            rec_stack.discard(node)

        for symbol in self._all_symbols:
            if symbol not in visited:
                dfs(symbol, [])

        return cycles

    def compute_fan_in(self) -> dict[str, int]:
        """Compute fan-in (number of distinct callers) for each symbol.
        
        Returns:
            Dict mapping qualified_name -> fan_in count
        """
        result = {}
        for symbol in self._all_symbols:
            result[symbol] = len(self._reverse_graph.get(symbol, set()))
        return result

    def compute_fan_out(self) -> dict[str, int]:
        """Compute fan-out (number of distinct callees) for each symbol.
        
        Returns:
            Dict mapping qualified_name -> fan_out count
        """
        result = {}
        for symbol in self._all_symbols:
            result[symbol] = len(self._graph.get(symbol, set()))
        return result

    def compute_call_depth(self) -> dict[str, int]:
        """Compute maximum call depth from leaf nodes (roots of invocation).
        
        Uses BFS from leaf nodes (symbols that are not callers).
        
        Returns:
            Dict mapping qualified_name -> max depth
        """
        # Identify root nodes (symbols with no incoming calls)
        roots = {sym for sym in self._all_symbols if not self._reverse_graph.get(sym, set())}
        
        result = {sym: 0 for sym in self._all_symbols}
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(sym, 0) for sym in roots])

        while queue:
            node, depth = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            result[node] = max(result[node], depth)

            for callee in self._graph.get(node, set()):
                if callee not in visited:
                    queue.append((callee, depth + 1))

        return result

    def find_critical_functions(self, top_n: int = 10) -> list[tuple[str, int]]:
        """Find most critical functions (high fan-in, central in call graph).
        
        Uses a combined score: (fan_in * 0.6) + (normalized_centrality * 0.4)
        
        Returns:
            List of (qualified_name, score) tuples, sorted by score descending
        """
        fan_in = self.compute_fan_in()
        fan_out = self.compute_fan_out()

        # Compute basic centrality: functions called by many and call many
        scores: dict[str, float] = {}
        max_fan_in = max(fan_in.values()) if fan_in else 1
        max_fan_out = max(fan_out.values()) if fan_out else 1

        for symbol in self._all_symbols:
            in_count = fan_in.get(symbol, 0)
            out_count = fan_out.get(symbol, 0)
            
            # Higher fan-in is more critical (more dependencies)
            # Moderate fan-out suggests coordination
            in_score = in_count / max_fan_in if max_fan_in > 0 else 0
            out_score = (out_count / max_fan_out if max_fan_out > 0 else 0) * 0.5
            
            scores[symbol] = (in_score * 0.6) + (out_score * 0.4)

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(name, int(score * 100)) for name, score in ranked[:top_n]]

    def compute_metrics(self) -> GraphMetrics:
        """Compute comprehensive graph metrics.
        
        Returns:
            GraphMetrics object with overall statistics
        """
        cycles = self.detect_cycles()
        fan_in = self.compute_fan_in()
        fan_out = self.compute_fan_out()

        symbols_in_cycles: set[str] = set()
        for cycle in cycles:
            symbols_in_cycles.update(cycle.symbols)

        total_calls = sum(len(callees) for callees in self._graph.values())
        avg_fan_in = sum(fan_in.values()) / len(self._all_symbols) if self._all_symbols else 0
        avg_fan_out = sum(fan_out.values()) / len(self._all_symbols) if self._all_symbols else 0
        max_fan_in = max(fan_in.values()) if fan_in else 0
        max_fan_out = max(fan_out.values()) if fan_out else 0
        max_cycle_len = max((c.length for c in cycles), default=0)

        depths = self.compute_call_depth()
        max_depth = max(depths.values()) if depths else 0

        return GraphMetrics(
            total_symbols=len(self._all_symbols),
            total_calls=total_calls,
            symbols_with_cycles=len(symbols_in_cycles),
            total_cycles=len(cycles),
            max_cycle_length=max_cycle_len,
            avg_fan_in=round(avg_fan_in, 2),
            avg_fan_out=round(avg_fan_out, 2),
            max_fan_in=max_fan_in,
            max_fan_out=max_fan_out,
            max_call_depth=max_depth,
        )
