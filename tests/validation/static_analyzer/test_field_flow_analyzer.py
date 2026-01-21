"""Tests for the field flow analyzer."""

import pytest

from agent_actions.validation.static_analyzer import (
    AgentKind,
    DataFlowGraph,
    DataFlowNode,
    FieldFlowAnalyzer,
    InputRequirement,
    OutputSchema,
    StaticValidationResult,
)


def create_simple_graph():
    """Create a simple linear workflow graph: source -> extractor -> summarizer."""
    graph = DataFlowGraph()

    # Source node
    graph.add_node(
        DataFlowNode(
            name="source",
            agent_kind=AgentKind.SOURCE,
            output_schema=OutputSchema(is_dynamic=True),
        )
    )

    # Extractor node
    graph.add_node(
        DataFlowNode(
            name="extractor",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(
                schema_fields={"summary", "facts", "confidence"},
            ),
            dependencies=set(),
            input_requirements=[
                InputRequirement("source", "content", "prompt", "{{ source.content }}"),
            ],
        )
    )

    # Summarizer node
    graph.add_node(
        DataFlowNode(
            name="summarizer",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(
                schema_fields={"final_summary"},
            ),
            dependencies={"extractor"},
            input_requirements=[
                InputRequirement(
                    "extractor", "summary", "prompt", "{{ action.extractor.summary }}"
                ),
                InputRequirement("extractor", "facts", "prompt", "{{ action.extractor.facts }}"),
            ],
        )
    )

    return graph


def create_graph_with_transformations():
    """Create a graph with observe, passthrough, and drop transformations."""
    graph = DataFlowGraph()

    # Source node
    graph.add_node(
        DataFlowNode(
            name="source",
            agent_kind=AgentKind.SOURCE,
            output_schema=OutputSchema(is_dynamic=True),
        )
    )

    # Processor with observe and drop
    graph.add_node(
        DataFlowNode(
            name="processor",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(
                schema_fields={"result", "score"},
                observe_fields={"original_content"},
                passthrough_fields={"metadata"},
                dropped_fields={"score"},  # Drop score field
            ),
            dependencies=set(),
            input_requirements=[
                InputRequirement("source", "content", "prompt", "{{ source.content }}"),
            ],
        )
    )

    return graph


class TestFieldConsumer:
    """Tests for FieldConsumer dataclass."""

    def test_to_dict(self):
        """Test FieldConsumer serialization."""
        from agent_actions.validation.static_analyzer import FieldConsumer

        consumer = FieldConsumer(
            agent="summarizer",
            location="prompt",
            raw_reference="{{ action.extractor.summary }}",
        )

        result = consumer.to_dict()

        assert result["agent"] == "summarizer"
        assert result["location"] == "prompt"
        assert result["raw_reference"] == "{{ action.extractor.summary }}"


class TestFieldLineage:
    """Tests for FieldLineage dataclass."""

    def test_to_dict(self):
        """Test FieldLineage serialization."""
        from agent_actions.validation.static_analyzer import FieldConsumer, FieldLineage

        lineage = FieldLineage(
            producer="extractor",
            field_name="summary",
            field_type="schema",
            consumers=[
                FieldConsumer("summarizer", "prompt", "{{ action.extractor.summary }}"),
            ],
            is_dropped=False,
        )

        result = lineage.to_dict()

        assert result["producer"] == "extractor"
        assert result["field_name"] == "summary"
        assert result["field_type"] == "schema"
        assert len(result["consumers"]) == 1
        assert result["is_dropped"] is False


class TestActionFlowInfo:
    """Tests for ActionFlowInfo dataclass."""

    def test_to_dict(self):
        """Test ActionFlowInfo serialization."""
        from agent_actions.validation.static_analyzer import (
            ActionFlowInfo,
            FieldReference,
            OutputFieldInfo,
        )

        action = ActionFlowInfo(
            name="extractor",
            kind="llm",
            inputs=[
                FieldReference("source", "content", "prompt", "{{ source.content }}"),
            ],
            outputs=OutputFieldInfo(
                schema_fields=["summary", "facts"],
                available_fields=["summary", "facts"],
            ),
            dependencies=[],
            downstream=["summarizer"],
        )

        result = action.to_dict()

        assert result["name"] == "extractor"
        assert result["kind"] == "llm"
        assert len(result["inputs"]) == 1
        assert result["outputs"]["schema_fields"] == ["summary", "facts"]
        assert result["downstream"] == ["summarizer"]


class TestFieldFlowAnalyzer:
    """Tests for FieldFlowAnalyzer class."""

    def test_get_full_flow_returns_all_actions(self):
        """Test that get_full_flow includes all actions in the workflow."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        flow = analyzer.get_full_flow()

        assert flow.workflow_name == "test_workflow"
        action_names = [a.name for a in flow.actions]
        assert "source" in action_names
        assert "extractor" in action_names
        assert "summarizer" in action_names

    def test_get_full_flow_correct_execution_order(self):
        """Test execution order respects dependencies."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        flow = analyzer.get_full_flow()

        # Extractor must come before summarizer
        extractor_idx = flow.execution_order.index("extractor")
        summarizer_idx = flow.execution_order.index("summarizer")
        assert extractor_idx < summarizer_idx

    def test_get_field_lineage_finds_producer(self):
        """Test lineage correctly identifies the producing action."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.get_field_lineage("extractor", "summary")

        assert lineage is not None
        assert lineage.producer == "extractor"
        assert lineage.field_name == "summary"
        assert lineage.field_type == "schema"

    def test_get_field_lineage_finds_all_consumers(self):
        """Test lineage finds all actions that consume a field."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.get_field_lineage("extractor", "summary")

        assert lineage is not None
        consumer_agents = [c.agent for c in lineage.consumers]
        assert "summarizer" in consumer_agents

    def test_get_field_lineage_nonexistent_field(self):
        """Test lineage returns None for nonexistent field."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.get_field_lineage("extractor", "nonexistent")

        assert lineage is None

    def test_get_field_lineage_nonexistent_agent(self):
        """Test lineage returns None for nonexistent agent."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.get_field_lineage("nonexistent", "summary")

        assert lineage is None

    def test_field_lineage_tracks_observe_fields(self):
        """Test observe fields are tracked with correct type."""
        graph = create_graph_with_transformations()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.get_field_lineage("processor", "original_content")

        assert lineage is not None
        assert lineage.field_type == "observe"

    def test_field_lineage_tracks_passthrough_fields(self):
        """Test passthrough fields are tracked with correct type."""
        graph = create_graph_with_transformations()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.get_field_lineage("processor", "metadata")

        assert lineage is not None
        assert lineage.field_type == "passthrough"

    def test_field_lineage_tracks_dropped_fields(self):
        """Test dropped fields are marked as dropped."""
        graph = create_graph_with_transformations()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.get_field_lineage("processor", "score")

        assert lineage is not None
        assert lineage.is_dropped is True

    def test_get_action_flow_info(self):
        """Test getting flow info for a single action."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        action_info = analyzer.get_action_flow_info("extractor")

        assert action_info is not None
        assert action_info.name == "extractor"
        assert action_info.kind == "llm"
        assert "summary" in action_info.outputs.schema_fields
        assert "facts" in action_info.outputs.schema_fields
        assert "summarizer" in action_info.downstream

    def test_get_action_flow_info_nonexistent(self):
        """Test getting flow info for nonexistent action returns None."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        action_info = analyzer.get_action_flow_info("nonexistent")

        assert action_info is None

    def test_to_dict_json_serializable(self):
        """Test output is valid JSON-serializable dict."""
        import json

        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        output = analyzer.to_dict()

        # Should not raise
        json_str = json.dumps(output)
        assert isinstance(json_str, str)

        # Verify structure
        assert "workflow" in output
        assert "is_valid" in output
        assert "flow" in output
        assert "validation" in output

    def test_filter_to_field(self):
        """Test filtering to a specific field."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.filter_to_field("extractor.summary")

        assert lineage is not None
        assert lineage.producer == "extractor"
        assert lineage.field_name == "summary"

    def test_filter_to_field_invalid_format(self):
        """Test filter with invalid format returns None."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.filter_to_field("no_dot_here")

        assert lineage is None


class TestWorkflowFlow:
    """Tests for WorkflowFlow dataclass."""

    def test_to_dict(self):
        """Test WorkflowFlow serialization."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        flow = analyzer.get_full_flow()
        result_dict = flow.to_dict()

        assert result_dict["workflow_name"] == "test_workflow"
        assert "actions" in result_dict
        assert "execution_order" in result_dict
        assert "field_lineages" in result_dict


class TestOutputFieldInfo:
    """Tests for OutputFieldInfo dataclass."""

    def test_to_dict(self):
        """Test OutputFieldInfo serialization."""
        from agent_actions.validation.static_analyzer import OutputFieldInfo

        info = OutputFieldInfo(
            schema_fields=["a", "b"],
            observe_fields=["c"],
            passthrough_fields=["d"],
            dropped_fields=["e"],
            available_fields=["a", "b", "c", "d"],
            is_dynamic=False,
            is_schemaless=False,
        )

        result = info.to_dict()

        assert result["schema_fields"] == ["a", "b"]
        assert result["observe_fields"] == ["c"]
        assert result["passthrough_fields"] == ["d"]
        assert result["dropped_fields"] == ["e"]
        assert result["is_dynamic"] is False
