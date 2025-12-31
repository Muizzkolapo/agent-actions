"""Tests for the data flow graph structures."""

import pytest

from agent_actions.validation.static_analyzer import (
    AgentKind,
    DataFlowEdge,
    DataFlowGraph,
    DataFlowNode,
    InputRequirement,
    InputSchema,
    OutputSchema,
)


class TestOutputSchema:
    """Tests for OutputSchema class."""

    def test_available_fields_with_schema_fields(self):
        """Test available_fields returns schema fields."""
        schema = OutputSchema(
            schema_fields={"name", "age", "email"},
        )

        assert schema.available_fields == {"name", "age", "email"}

    def test_available_fields_with_observe(self):
        """Test available_fields includes observed fields."""
        schema = OutputSchema(
            schema_fields={"name"},
            observe_fields={"age", "email"},
        )

        assert schema.available_fields == {"name", "age", "email"}

    def test_available_fields_with_drops(self):
        """Test available_fields excludes dropped fields."""
        schema = OutputSchema(
            schema_fields={"name", "age", "email"},
            dropped_fields={"email"},
        )

        assert schema.available_fields == {"name", "age"}

    def test_available_fields_formula(self):
        """Test available = (schema + observe) - dropped."""
        schema = OutputSchema(
            schema_fields={"a", "b"},
            observe_fields={"c", "d"},
            dropped_fields={"b", "c"},
        )

        # (a, b) + (c, d) - (b, c) = (a, d)
        assert schema.available_fields == {"a", "d"}

    def test_is_schemaless(self):
        """Test schemaless flag."""
        schema = OutputSchema(is_schemaless=True)
        assert schema.is_schemaless
        assert schema.available_fields == set()

    def test_is_dynamic(self):
        """Test dynamic schema flag."""
        schema = OutputSchema(is_dynamic=True)
        assert schema.is_dynamic

    def test_passthrough_fields(self):
        """Test passthrough fields are included in available."""
        schema = OutputSchema(
            schema_fields={"a"},
            passthrough_fields={"b", "c"},
        )
        assert "a" in schema.available_fields
        assert "b" in schema.available_fields
        assert "c" in schema.available_fields


class TestInputSchema:
    """Tests for InputSchema class."""

    def test_all_fields(self):
        """Test all_fields returns required + optional."""
        schema = InputSchema(
            required_fields={"name", "email"},
            optional_fields={"age", "phone"},
        )

        assert schema.all_fields == {"name", "email", "age", "phone"}

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

    def test_is_template_based(self):
        """Test template-based flag for LLM agents."""
        schema = InputSchema(is_template_based=True)
        assert schema.is_template_based
        assert len(schema.all_fields) == 0

    def test_is_dynamic(self):
        """Test dynamic input schema flag."""
        schema = InputSchema(is_dynamic=True)
        assert schema.is_dynamic


class TestInputRequirement:
    """Tests for InputRequirement class."""

    def test_basic_requirement(self):
        """Test basic input requirement."""
        req = InputRequirement(
            source_agent="extractor",
            field_path="summary",
            location="prompt",
            raw_reference="{{ action.extractor.summary }}",
        )

        assert req.source_agent == "extractor"
        assert req.field_path == "summary"
        assert req.location == "prompt"

    def test_nested_field_path(self):
        """Test requirement with nested field path."""
        req = InputRequirement(
            source_agent="analyzer",
            field_path="metadata.score",
            location="guard",
            raw_reference="{{ action.analyzer.metadata.score }}",
        )

        assert req.field_path == "metadata.score"


class TestDataFlowNode:
    """Tests for DataFlowNode class."""

    def test_basic_node(self):
        """Test basic node creation."""
        node = DataFlowNode(
            name="processor",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"result"}),
        )

        assert node.name == "processor"
        assert node.agent_kind == AgentKind.LLM
        assert node.output_schema.available_fields == {"result"}
        assert node.dependencies == set()
        assert node.input_requirements == []

    def test_node_with_dependencies(self):
        """Test node with dependencies."""
        node = DataFlowNode(
            name="summarizer",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"summary"}),
            dependencies={"extractor", "classifier"},
        )

        assert node.dependencies == {"extractor", "classifier"}

    def test_node_with_input_requirements(self):
        """Test node with input requirements."""
        reqs = [
            InputRequirement("extractor", "text", "prompt", ""),
            InputRequirement("classifier", "category", "prompt", ""),
        ]

        node = DataFlowNode(
            name="processor",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"result"}),
            input_requirements=reqs,
        )

        assert len(node.input_requirements) == 2


class TestDataFlowEdge:
    """Tests for DataFlowEdge class."""

    def test_edge_creation(self):
        """Test edge creation."""
        edge = DataFlowEdge(
            source="extractor",
            target="summarizer",
            fields_used={"text", "metadata"},
        )

        assert edge.source == "extractor"
        assert edge.target == "summarizer"
        assert edge.fields_used == {"text", "metadata"}


class TestDataFlowGraph:
    """Tests for DataFlowGraph class."""

    def test_add_node(self):
        """Test adding nodes to graph."""
        graph = DataFlowGraph()

        node = DataFlowNode(
            name="agent1",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"result"}),
        )
        graph.add_node(node)

        assert "agent1" in graph.nodes
        assert graph.get_node("agent1") is node

    def test_get_nonexistent_node(self):
        """Test getting nonexistent node returns None."""
        graph = DataFlowGraph()
        assert graph.get_node("missing") is None

    def test_topological_sort_simple(self):
        """Test topological sort with simple dependencies."""
        graph = DataFlowGraph()

        # A -> B -> C
        graph.add_node(
            DataFlowNode(
                name="A",
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=AgentKind.LLM,
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
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="D",
                agent_kind=AgentKind.LLM,
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
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"C"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"B"},
            )
        )

        with pytest.raises(ValueError, match="[Cc]ircular|[Cc]ycle"):
            graph.topological_sort()

    def test_special_namespaces(self):
        """Test special namespaces are recognized."""
        graph = DataFlowGraph()

        assert graph.is_special_namespace("source")
        assert graph.is_special_namespace("loop")
        assert graph.is_special_namespace("workflow")
        assert graph.is_special_namespace("seed")
        assert not graph.is_special_namespace("my_agent")

    def test_get_all_agent_names(self):
        """Test getting all agent names excludes special namespaces."""
        graph = DataFlowGraph()

        # Add source node (special)
        graph.add_node(
            DataFlowNode(
                name="source",
                agent_kind=AgentKind.SOURCE,
                output_schema=OutputSchema(is_dynamic=True),
            )
        )

        # Add regular agents
        graph.add_node(
            DataFlowNode(
                name="agent1",
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="agent2",
                agent_kind=AgentKind.TOOL,
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
                agent_kind=AgentKind.SOURCE,
                output_schema=OutputSchema(is_dynamic=True),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="agent1",
                agent_kind=AgentKind.LLM,
                output_schema=OutputSchema(schema_fields={"text"}),
            )
        )
        graph.add_node(
            DataFlowNode(
                name="agent2",
                agent_kind=AgentKind.LLM,
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
