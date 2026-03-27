"""J-4: Coverage of DataFlowGraph.topological_sort() — DAG, cycle detection, O(n) fix (D-7)."""

import pytest

from agent_actions.config.schema import ActionKind
from agent_actions.validation.static_analyzer.data_flow_graph import (
    DataFlowGraph,
    DataFlowNode,
    InputSchema,
    OutputSchema,
)


def _make_node(name: str, deps: set[str] | None = None) -> DataFlowNode:
    return DataFlowNode(
        name=name,
        agent_kind=ActionKind.LLM,
        output_schema=OutputSchema(),
        input_schema=InputSchema(),
        dependencies=deps or set(),
    )


class TestTopologicalSortDAG:
    """topological_sort on valid DAGs."""

    def test_empty_graph(self):
        g = DataFlowGraph()
        result = g.topological_sort()
        assert result == []

    def test_single_node(self):
        g = DataFlowGraph()
        g.add_node(_make_node("a"))
        result = g.topological_sort()
        assert result == ["a"]

    def test_linear_chain(self):
        """a -> b -> c must produce [a, b, c]."""
        g = DataFlowGraph()
        g.add_node(_make_node("a"))
        g.add_node(_make_node("b", {"a"}))
        g.add_node(_make_node("c", {"b"}))
        result = g.topological_sort()
        # a before b, b before c
        assert result.index("a") < result.index("b")
        assert result.index("b") < result.index("c")

    def test_diamond_dag(self):
        """
        a -> b \\
              -> d
        a -> c /
        """
        g = DataFlowGraph()
        g.add_node(_make_node("a"))
        g.add_node(_make_node("b", {"a"}))
        g.add_node(_make_node("c", {"a"}))
        g.add_node(_make_node("d", {"b", "c"}))
        result = g.topological_sort()
        assert len(result) == 4
        assert result.index("a") < result.index("b")
        assert result.index("a") < result.index("c")
        assert result.index("b") < result.index("d")
        assert result.index("c") < result.index("d")

    def test_parallel_independent_nodes(self):
        g = DataFlowGraph()
        g.add_node(_make_node("x"))
        g.add_node(_make_node("y"))
        g.add_node(_make_node("z"))
        result = g.topological_sort()
        assert sorted(result) == ["x", "y", "z"]

    def test_all_nodes_returned(self):
        g = DataFlowGraph()
        nodes = ["a", "b", "c", "d", "e"]
        g.add_node(_make_node("a"))
        g.add_node(_make_node("b", {"a"}))
        g.add_node(_make_node("c", {"a"}))
        g.add_node(_make_node("d", {"b", "c"}))
        g.add_node(_make_node("e", {"d"}))
        result = g.topological_sort()
        assert sorted(result) == sorted(nodes)


class TestTopologicalSortCycleDetection:
    """topological_sort raises ValueError on cycles."""

    def test_simple_cycle(self):
        g = DataFlowGraph()
        g.add_node(_make_node("a", {"b"}))
        g.add_node(_make_node("b", {"a"}))
        with pytest.raises(ValueError, match="[Cc]ircular"):
            g.topological_sort()

    def test_self_loop(self):
        g = DataFlowGraph()
        g.add_node(_make_node("a", {"a"}))
        with pytest.raises(ValueError, match="[Cc]ircular"):
            g.topological_sort()

    def test_three_node_cycle(self):
        g = DataFlowGraph()
        g.add_node(_make_node("a", {"c"}))
        g.add_node(_make_node("b", {"a"}))
        g.add_node(_make_node("c", {"b"}))
        with pytest.raises(ValueError, match="[Cc]ircular"):
            g.topological_sort()


class TestTopologicalSortOneFix:
    """Verify D-7 correctness: O(n) adjacency map produces same result as brute-force."""

    def test_large_linear_chain_correct(self):
        """A long chain of 20 nodes should sort correctly with the O(n) fix."""
        g = DataFlowGraph()
        names = [f"node_{i}" for i in range(20)]
        g.add_node(_make_node(names[0]))
        for i in range(1, 20):
            g.add_node(_make_node(names[i], {names[i - 1]}))
        result = g.topological_sort()
        assert len(result) == 20
        for i in range(1, 20):
            assert result.index(names[i - 1]) < result.index(names[i])

    def test_wide_fan_out(self):
        """One root node with 10 dependents: root must come first."""
        g = DataFlowGraph()
        g.add_node(_make_node("root"))
        for i in range(10):
            g.add_node(_make_node(f"leaf_{i}", {"root"}))
        result = g.topological_sort()
        assert result[0] == "root"
        assert len(result) == 11
