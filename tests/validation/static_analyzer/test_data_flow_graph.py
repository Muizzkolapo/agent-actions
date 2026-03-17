"""Tests for the data flow graph structures."""

import pytest

from agent_actions.validation.static_analyzer import (
    ActionKind,
    DataFlowGraph,
    DataFlowNode,
    InputRequirement,
    InputSchema,
    OutputSchema,
)


class TestOutputSchema:
    """Tests for OutputSchema class."""

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            pytest.param(
                {"schema_fields": {"name", "age", "email"}},
                {"name", "age", "email"},
                id="schema_only",
            ),
            pytest.param(
                {"schema_fields": {"name"}, "observe_fields": {"age", "email"}},
                {"name", "age", "email"},
                id="with_observe",
            ),
            pytest.param(
                {"schema_fields": {"name", "age", "email"}, "dropped_fields": {"email"}},
                {"name", "age"},
                id="with_drops",
            ),
            pytest.param(
                {
                    "schema_fields": {"a", "b"},
                    "observe_fields": {"c", "d"},
                    "dropped_fields": {"b", "c"},
                },
                {"a", "d"},
                id="formula",
            ),
        ],
    )
    def test_available_fields(self, kwargs, expected):
        schema = OutputSchema(**kwargs)
        assert schema.available_fields == expected


class TestInputSchema:
    """Tests for InputSchema class."""

    def test_requires_field(self):
        """Test requires_field returns True for required fields."""
        schema = InputSchema(
            required_fields={"name"},
            optional_fields={"age"},
        )

        assert schema.requires_field("name")
        assert not schema.requires_field("age")
        assert not schema.requires_field("unknown")

    def test_accepts_field(self):
        """Test accepts_field returns True for any known field."""
        schema = InputSchema(
            required_fields={"name"},
            optional_fields={"age"},
        )

        assert schema.accepts_field("name")
        assert schema.accepts_field("age")
        assert not schema.accepts_field("unknown")


class TestDataFlowGraph:
    """Tests for DataFlowGraph class."""

    def test_topological_sort_simple(self):
        """Test topological sort with simple dependencies."""
        graph = DataFlowGraph()

        # A -> B -> C
        graph.add_node(
            DataFlowNode(
                name="A",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"B"},
            )
        )

        order = graph.topological_sort()

        # A must come before B, B must come before C
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")

    def test_topological_sort_diamond(self):
        """Test topological sort with diamond dependency pattern."""
        graph = DataFlowGraph()

        # A -> B, A -> C, B -> D, C -> D
        graph.add_node(
            DataFlowNode(
                name="A",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="D",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"B", "C"},
            )
        )

        order = graph.topological_sort()

        # A must come first, D must come last
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_topological_sort_detects_cycle(self):
        """Test topological sort detects circular dependencies."""
        graph = DataFlowGraph()

        # A -> B -> C -> A (cycle)
        graph.add_node(
            DataFlowNode(
                name="A",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"C"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"B"},
            )
        )

        with pytest.raises(ValueError, match="[Cc]ircular|[Cc]ycle"):
            graph.topological_sort()

    @pytest.mark.parametrize(
        "namespace,expected",
        [
            pytest.param("source", True, id="source"),
            pytest.param("version", True, id="version"),
            pytest.param("workflow", True, id="workflow"),
            pytest.param("seed", True, id="seed"),
            pytest.param("my_agent", False, id="regular_agent"),
        ],
    )
    def test_special_namespaces(self, namespace, expected):
        graph = DataFlowGraph()
        assert graph.is_special_namespace(namespace) is expected

    def test_get_all_agent_names(self):
        """Test getting all agent names excludes special namespaces."""
        graph = DataFlowGraph()

        # Add source node (special)
        graph.add_node(
            DataFlowNode(
                name="source",
                agent_kind=ActionKind.SOURCE,
                output_schema=OutputSchema(is_dynamic=True),
            )
        )

        # Add regular agents
        graph.add_node(
            DataFlowNode(
                name="agent1",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="agent2",
                agent_kind=ActionKind.TOOL,
                output_schema=OutputSchema(schema_fields={"result"}),
            )
        )

        agent_names = graph.get_all_agent_names()

        assert "agent1" in agent_names
        assert "agent2" in agent_names
        assert "source" not in agent_names

    def test_build_edges_from_requirements(self):
        """Test building edges from input requirements."""
        graph = DataFlowGraph()

        graph.add_node(
            DataFlowNode(
                name="source",
                agent_kind=ActionKind.SOURCE,
                output_schema=OutputSchema(is_dynamic=True),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="agent1",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"text"}),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="agent2",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"summary"}),
                dependencies={"agent1"},
                input_requirements=[
                    InputRequirement("agent1", "text", "prompt", "{{ action.agent1.text }}"),
                ],
            )
        )

        graph.build_edges_from_requirements()

        # Should have edge from agent1 to agent2
        assert len(graph.edges) >= 1
        edge = [e for e in graph.edges if e.source == "agent1" and e.target == "agent2"]
        assert len(edge) == 1
        assert "text" in edge[0].fields_used
