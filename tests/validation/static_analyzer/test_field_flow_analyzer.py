"""Tests for the field flow analyzer."""

import pytest

from agent_actions.validation.static_analyzer import (
    ActionKind,
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
            agent_kind=ActionKind.SOURCE,
            output_schema=OutputSchema(is_dynamic=True),
        )
    )

    # Extractor node
    graph.add_node(
        DataFlowNode(
            name="extractor",
            agent_kind=ActionKind.LLM,
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
            agent_kind=ActionKind.LLM,
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
            agent_kind=ActionKind.SOURCE,
            output_schema=OutputSchema(is_dynamic=True),
        )
    )

    # Processor with observe and drop
    graph.add_node(
        DataFlowNode(
            name="processor",
            agent_kind=ActionKind.LLM,
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

    @pytest.mark.parametrize(
        "agent,field",
        [
            pytest.param("extractor", "nonexistent", id="nonexistent_field"),
            pytest.param("nonexistent", "summary", id="nonexistent_agent"),
        ],
    )
    def test_get_field_lineage_nonexistent(self, agent, field):
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.get_field_lineage(agent, field)

        assert lineage is None

    @pytest.mark.parametrize(
        "field,expected_type,expected_dropped",
        [
            pytest.param("original_content", "observe", False, id="observe"),
            pytest.param("metadata", "passthrough", False, id="passthrough"),
            pytest.param("score", None, True, id="dropped"),
        ],
    )
    def test_field_lineage_tracks_field_types(self, field, expected_type, expected_dropped):
        graph = create_graph_with_transformations()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.get_field_lineage("processor", field)

        assert lineage is not None
        if expected_type is not None:
            assert lineage.field_type == expected_type
        assert lineage.is_dropped is expected_dropped

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

    def test_filter_to_field(self):
        """Test filtering to a specific field."""
        graph = create_simple_graph()
        result = StaticValidationResult()
        analyzer = FieldFlowAnalyzer(graph, result, "test_workflow")

        lineage = analyzer.filter_to_field("extractor.summary")

        assert lineage is not None
        assert lineage.producer == "extractor"
        assert lineage.field_name == "summary"
