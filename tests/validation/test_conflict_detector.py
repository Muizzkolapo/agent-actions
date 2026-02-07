"""Tests for conflict detector functionality."""

import pytest

from agent_actions.validation.static_analyzer import (
    AffectedReference,
    Conflict,
    ConflictAnalysisResult,
    ConflictDetector,
    ConflictSeverity,
    ConflictType,
    FieldProducer,
)
from agent_actions.validation.static_analyzer.data_flow_graph import (
    AgentKind,
    DataFlowGraph,
    DataFlowNode,
    InputRequirement,
    OutputSchema,
)


class TestConflictAnalysisResult:
    """Tests for ConflictAnalysisResult dataclass."""

    @pytest.mark.parametrize(
        "conflicts,expected",
        [
            pytest.param([], False, id="empty"),
            pytest.param(
                [
                    Conflict(
                        conflict_type=ConflictType.SHADOWING,
                        severity=ConflictSeverity.WARNING,
                        field_name="title",
                        message="Test",
                        resolution="Fix it",
                    )
                ],
                True,
                id="with_conflicts",
            ),
        ],
    )
    def test_has_conflicts(self, conflicts, expected):
        result = ConflictAnalysisResult(workflow_name="test", conflicts=conflicts)
        assert result.has_conflicts is expected

    def test_error_count(self):
        """Test error_count property."""
        result = ConflictAnalysisResult(
            workflow_name="test",
            conflicts=[
                Conflict(
                    conflict_type=ConflictType.SHADOWING,
                    severity=ConflictSeverity.ERROR,
                    field_name="a",
                    message="",
                    resolution="",
                ),
                Conflict(
                    conflict_type=ConflictType.SHADOWING,
                    severity=ConflictSeverity.ERROR,
                    field_name="b",
                    message="",
                    resolution="",
                ),
                Conflict(
                    conflict_type=ConflictType.SHADOWING,
                    severity=ConflictSeverity.WARNING,
                    field_name="c",
                    message="",
                    resolution="",
                ),
            ],
        )
        assert result.error_count == 2
        assert result.warning_count == 1

    def test_filter_by_action(self):
        """Test filtering conflicts by action."""
        result = ConflictAnalysisResult(
            workflow_name="test",
            conflicts=[
                Conflict(
                    conflict_type=ConflictType.SHADOWING,
                    severity=ConflictSeverity.WARNING,
                    field_name="title",
                    message="Test",
                    resolution="Fix it",
                    producers=[FieldProducer("extractor", "schema")],
                ),
                Conflict(
                    conflict_type=ConflictType.SHADOWING,
                    severity=ConflictSeverity.WARNING,
                    field_name="summary",
                    message="Test",
                    resolution="Fix it",
                    producers=[FieldProducer("summarizer", "schema")],
                ),
            ],
            actions_analyzed=3,
        )
        filtered = result.filter_by_action("extractor")
        assert len(filtered.conflicts) == 1
        assert filtered.conflicts[0].field_name == "title"

    def test_filter_by_action_with_affected_refs(self):
        """Test filtering includes affected references."""
        result = ConflictAnalysisResult(
            workflow_name="test",
            conflicts=[
                Conflict(
                    conflict_type=ConflictType.AMBIGUOUS_REFERENCE,
                    severity=ConflictSeverity.ERROR,
                    field_name="title",
                    message="Test",
                    resolution="Fix it",
                    producers=[FieldProducer("extractor", "schema")],
                    affected_references=[AffectedReference("consumer", "task", "{{ title }}")],
                ),
            ],
        )
        # Should match when action is a consumer
        filtered = result.filter_by_action("consumer")
        assert len(filtered.conflicts) == 1


class TestConflictDetector:
    """Tests for ConflictDetector class."""

    def _create_simple_graph(self) -> DataFlowGraph:
        """Create a simple graph for testing."""
        graph = DataFlowGraph()

        # Add source node
        source_node = DataFlowNode(
            name="source",
            agent_kind=AgentKind.SOURCE,
            output_schema=OutputSchema(schema_fields={"input_text"}),
        )
        graph.add_node(source_node)

        # Add extractor
        extractor_node = DataFlowNode(
            name="extractor",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"title", "summary"}),
            input_requirements=[
                InputRequirement(
                    source_agent="source",
                    field_path="input_text",
                    location="task_instructions",
                    raw_reference="{{ source.input_text }}",
                )
            ],
            dependencies={"source"},
        )
        graph.add_node(extractor_node)

        return graph

    def test_no_conflicts(self):
        """Test workflow with no conflicts."""
        graph = self._create_simple_graph()
        detector = ConflictDetector(graph, "test_workflow")
        result = detector.detect_all()

        assert not result.has_conflicts
        assert result.actions_analyzed == 1  # excludes source
        assert result.unique_fields == 2  # title, summary

    def test_detect_shadowing(self):
        """Test detection of shadowing conflicts."""
        graph = DataFlowGraph()

        # Two actions producing same field
        action1 = DataFlowNode(
            name="action1",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"shared_field"}),
        )
        action2 = DataFlowNode(
            name="action2",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"shared_field"}),
        )
        graph.add_node(action1)
        graph.add_node(action2)

        detector = ConflictDetector(graph, "test")
        result = detector.detect_all()

        shadowing_conflicts = [
            c for c in result.conflicts if c.conflict_type == ConflictType.SHADOWING
        ]
        assert len(shadowing_conflicts) == 1
        assert shadowing_conflicts[0].field_name == "shared_field"
        assert shadowing_conflicts[0].severity == ConflictSeverity.WARNING

    def test_detect_ambiguous_reference(self):
        """Test detection of ambiguous references."""
        graph = DataFlowGraph()

        # Source with a field
        source = DataFlowNode(
            name="source",
            agent_kind=AgentKind.SOURCE,
            output_schema=OutputSchema(schema_fields={"ambiguous"}),
        )
        graph.add_node(source)

        # Two actions producing same field name
        action1 = DataFlowNode(
            name="action1",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"ambiguous"}),
        )
        action2 = DataFlowNode(
            name="action2",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"ambiguous"}),
        )
        graph.add_node(action1)
        graph.add_node(action2)

        # Action referencing the ambiguous field via source namespace
        consumer = DataFlowNode(
            name="consumer",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"result"}),
            input_requirements=[
                InputRequirement(
                    source_agent="source",
                    field_path="ambiguous",
                    location="task_instructions",
                    raw_reference="{{ source.ambiguous }}",
                )
            ],
            dependencies={"action1", "action2"},
        )
        graph.add_node(consumer)

        detector = ConflictDetector(graph, "test")
        result = detector.detect_all()

        ambiguous_conflicts = [
            c for c in result.conflicts if c.conflict_type == ConflictType.AMBIGUOUS_REFERENCE
        ]
        assert len(ambiguous_conflicts) == 1
        assert ambiguous_conflicts[0].severity == ConflictSeverity.ERROR

    def test_detect_reserved_names(self):
        """Test detection of reserved name usage."""
        graph = DataFlowGraph()

        # Action producing a reserved field name
        action = DataFlowNode(
            name="bad_action",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"source", "regular_field"}),
        )
        graph.add_node(action)

        detector = ConflictDetector(graph, "test")
        result = detector.detect_all()

        reserved_conflicts = [
            c for c in result.conflicts if c.conflict_type == ConflictType.RESERVED_NAME
        ]
        assert len(reserved_conflicts) == 1
        assert reserved_conflicts[0].field_name == "source"
        assert reserved_conflicts[0].severity == ConflictSeverity.WARNING

    def test_detect_drop_recreate(self):
        """Test detection of drop-recreate patterns."""
        graph = DataFlowGraph()

        # First action produces and drops a field
        action1 = DataFlowNode(
            name="action1",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(
                schema_fields={"temp_field"},
                dropped_fields={"temp_field"},
            ),
        )
        graph.add_node(action1)

        # Second action recreates the field
        action2 = DataFlowNode(
            name="action2",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"temp_field"}),
        )
        graph.add_node(action2)

        detector = ConflictDetector(graph, "test")
        result = detector.detect_all()

        drop_recreate_conflicts = [
            c for c in result.conflicts if c.conflict_type == ConflictType.DROP_RECREATE
        ]
        assert len(drop_recreate_conflicts) == 1
        assert drop_recreate_conflicts[0].severity == ConflictSeverity.INFO

    def test_get_shadowed_fields(self):
        """Test get_shadowed_fields helper method."""
        graph = DataFlowGraph()

        action1 = DataFlowNode(
            name="action1",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"shared", "unique1"}),
        )
        action2 = DataFlowNode(
            name="action2",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"shared", "unique2"}),
        )
        graph.add_node(action1)
        graph.add_node(action2)

        detector = ConflictDetector(graph, "test")
        shadowed = detector.get_shadowed_fields()

        assert "shared" in shadowed
        assert set(shadowed["shared"]) == {"action1", "action2"}
        assert "unique1" not in shadowed
        assert "unique2" not in shadowed

    def test_observe_field_conflicts(self):
        """Test that observe fields are tracked for conflicts."""
        graph = DataFlowGraph()

        # Action with schema field
        action1 = DataFlowNode(
            name="action1",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"shared"}),
        )
        # Action with observe field of same name
        action2 = DataFlowNode(
            name="action2",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(observe_fields={"shared"}),
        )
        graph.add_node(action1)
        graph.add_node(action2)

        detector = ConflictDetector(graph, "test")
        result = detector.detect_all()

        shadowing = [c for c in result.conflicts if c.conflict_type == ConflictType.SHADOWING]
        assert len(shadowing) == 1
        # Check producers have different sources
        sources = {p.field_source for p in shadowing[0].producers}
        assert sources == {"schema", "observe"}

    def test_passthrough_field_conflicts(self):
        """Test that passthrough fields are tracked for conflicts."""
        graph = DataFlowGraph()

        action1 = DataFlowNode(
            name="action1",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"field1"}),
        )
        action2 = DataFlowNode(
            name="action2",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(passthrough_fields={"field1"}),
        )
        graph.add_node(action1)
        graph.add_node(action2)

        detector = ConflictDetector(graph, "test")
        result = detector.detect_all()

        shadowing = [c for c in result.conflicts if c.conflict_type == ConflictType.SHADOWING]
        assert len(shadowing) == 1

    def test_dropped_fields_not_counted(self):
        """Test that dropped fields don't count as conflicts."""
        graph = DataFlowGraph()

        # Both produce same field but one drops it
        action1 = DataFlowNode(
            name="action1",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(
                schema_fields={"field1"},
                dropped_fields={"field1"},
            ),
        )
        action2 = DataFlowNode(
            name="action2",
            agent_kind=AgentKind.LLM,
            output_schema=OutputSchema(schema_fields={"field1"}),
        )
        graph.add_node(action1)
        graph.add_node(action2)

        detector = ConflictDetector(graph, "test")
        result = detector.detect_all()

        # Should not be a shadowing conflict since action1 drops the field
        shadowing = [c for c in result.conflicts if c.conflict_type == ConflictType.SHADOWING]
        assert len(shadowing) == 0

    def test_empty_graph(self):
        """Test with empty graph."""
        graph = DataFlowGraph()
        detector = ConflictDetector(graph, "empty")
        result = detector.detect_all()

        assert not result.has_conflicts
        assert result.actions_analyzed == 0
        assert result.unique_fields == 0
