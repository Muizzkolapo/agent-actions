"""Tests for drop directives and lineage reachability in WorkflowStaticAnalyzer."""

from agent_actions.config.schema import ActionKind
from agent_actions.validation.static_analyzer.data_flow_graph import (
    DataFlowGraph,
    DataFlowNode,
    OutputSchema,
)
from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


def _build_analyzer_with_graph(workflow_config, graph):
    """Build a WorkflowStaticAnalyzer and inject a pre-built graph."""
    analyzer = WorkflowStaticAnalyzer(workflow_config)
    analyzer.graph = graph
    analyzer._built = True
    return analyzer


class TestCheckDropDirectives:
    """Tests for _check_drop_directives()."""

    def _make_graph_with_upstream(
        self,
        schema_fields=None,
        observe_fields=None,
        passthrough_fields=None,
        is_dynamic=False,
        is_schemaless=False,
    ):
        """Build a graph with source -> upstream_action -> downstream_action."""
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
                name="upstream",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(
                    schema_fields=schema_fields or set(),
                    observe_fields=observe_fields or set(),
                    passthrough_fields=passthrough_fields or set(),
                    is_dynamic=is_dynamic,
                    is_schemaless=is_schemaless,
                ),
                dependencies={"source"},
            )
        )
        return graph

    def test_drop_on_schema_field_no_error(self):
        """Drop on a schema field produces no error."""
        graph = self._make_graph_with_upstream(schema_fields={"summary", "title"})
        workflow_config = {
            "actions": [
                {
                    "name": "downstream",
                    "depends_on": ["upstream"],
                    "context_scope": {
                        "drop": ["upstream.summary"],
                        "observe": ["upstream.title"],
                    },
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        errors = analyzer._check_drop_directives()
        assert len(errors) == 0

    def test_drop_on_passthrough_field_produces_error(self):
        """Drop on a passthrough field produces an error with a hint about passthrough."""
        graph = self._make_graph_with_upstream(
            schema_fields={"summary"},
            passthrough_fields={"forwarded_field"},
        )
        workflow_config = {
            "actions": [
                {
                    "name": "downstream",
                    "depends_on": ["upstream"],
                    "context_scope": {
                        "drop": ["upstream.forwarded_field"],
                    },
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        errors = analyzer._check_drop_directives()
        assert len(errors) == 1
        assert "passthrough" in errors[0].message.lower()
        assert "forwarded_field" in errors[0].message

    def test_drop_on_nonexistent_field_produces_error(self):
        """Drop on a non-existent field produces an error with available fields."""
        graph = self._make_graph_with_upstream(schema_fields={"summary", "title"})
        workflow_config = {
            "actions": [
                {
                    "name": "downstream",
                    "depends_on": ["upstream"],
                    "context_scope": {
                        "drop": ["upstream.nonexistent"],
                    },
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        errors = analyzer._check_drop_directives()
        assert len(errors) == 1
        msg = errors[0].message.lower()
        assert "non-existent" in msg or "nonexistent" in msg
        assert errors[0].available_fields  # Should have available fields

    def test_drop_with_wildcard_no_error(self):
        """Drop with wildcard produces no error."""
        graph = self._make_graph_with_upstream(schema_fields={"summary"})
        workflow_config = {
            "actions": [
                {
                    "name": "downstream",
                    "depends_on": ["upstream"],
                    "context_scope": {
                        "drop": ["upstream.*"],
                    },
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        errors = analyzer._check_drop_directives()
        assert len(errors) == 0

    def test_drop_on_dynamic_schema_no_error(self):
        """Drop on a dynamic schema produces no error (skipped)."""
        graph = self._make_graph_with_upstream(is_dynamic=True)
        workflow_config = {
            "actions": [
                {
                    "name": "downstream",
                    "depends_on": ["upstream"],
                    "context_scope": {
                        "drop": ["upstream.anything"],
                    },
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        errors = analyzer._check_drop_directives()
        assert len(errors) == 0

    def test_drop_on_observe_field_no_error(self):
        """Drop on an observe field (not schema) produces no error."""
        graph = self._make_graph_with_upstream(
            schema_fields={"summary"},
            observe_fields={"observed_field"},
        )
        workflow_config = {
            "actions": [
                {
                    "name": "downstream",
                    "depends_on": ["upstream"],
                    "context_scope": {
                        "drop": ["upstream.observed_field"],
                    },
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        errors = analyzer._check_drop_directives()
        assert len(errors) == 0


class TestCheckLineageReachability:
    """Tests for _check_lineage_reachability()."""

    def test_direct_dependency_observe_no_warning(self):
        """Observing a field from a direct dependency produces no warning."""
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
                name="A",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"field_x"}),
                dependencies={"source"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"result"}),
                dependencies={"A"},
            )
        )

        workflow_config = {
            "actions": [
                {"name": "A", "depends_on": ["source"]},
                {
                    "name": "B",
                    "depends_on": ["A"],
                    "context_scope": {"observe": ["A.field_x"]},
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        warnings = analyzer._check_lineage_reachability()
        assert len(warnings) == 0

    def test_transitive_observe_with_wildcard_passthrough_no_warning(self):
        """Transitive observe with wildcard passthrough produces no warning."""
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
                name="A",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"field_x"}),
                dependencies={"source"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(
                    schema_fields={"result"},
                    passthrough_wildcard_sources={"A"},
                ),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"final"}),
                dependencies={"B"},
            )
        )

        workflow_config = {
            "actions": [
                {"name": "A", "depends_on": ["source"]},
                {
                    "name": "B",
                    "depends_on": ["A"],
                    "context_scope": {"passthrough": ["A.*"]},
                },
                {
                    "name": "C",
                    "depends_on": ["B"],
                    "context_scope": {"observe": ["A.field_x"]},
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        warnings = analyzer._check_lineage_reachability()
        assert len(warnings) == 0

    def test_transitive_observe_with_explicit_field_passthrough_no_warning(self):
        """Transitive observe with explicit field passthrough produces no warning."""
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
                name="A",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"field_x"}),
                dependencies={"source"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(
                    schema_fields={"result"},
                    passthrough_fields={"field_x"},
                ),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"final"}),
                dependencies={"B"},
            )
        )

        workflow_config = {
            "actions": [
                {"name": "A", "depends_on": ["source"]},
                {
                    "name": "B",
                    "depends_on": ["A"],
                    "context_scope": {"passthrough": ["A.field_x"]},
                },
                {
                    "name": "C",
                    "depends_on": ["B"],
                    "context_scope": {"observe": ["A.field_x"]},
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        warnings = analyzer._check_lineage_reachability()
        assert len(warnings) == 0

    def test_transitive_observe_without_passthrough_produces_warning(self):
        """Transitive observe with NO passthrough produces a warning."""
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
                name="A",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"field_x"}),
                dependencies={"source"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"result"}),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"final"}),
                dependencies={"B"},
            )
        )

        workflow_config = {
            "actions": [
                {"name": "A", "depends_on": ["source"]},
                {"name": "B", "depends_on": ["A"]},
                {
                    "name": "C",
                    "depends_on": ["B"],
                    "context_scope": {"observe": ["A.field_x"]},
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        warnings = analyzer._check_lineage_reachability()
        assert len(warnings) == 1
        assert "field_x" in warnings[0].message
        assert "passthrough" in warnings[0].hint.lower()

    def test_dynamic_intermediate_no_warning(self):
        """Dynamic intermediate schema produces no warning (data may survive)."""
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
                name="A",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"field_x"}),
                dependencies={"source"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="B",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(is_dynamic=True),
                dependencies={"A"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="C",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"final"}),
                dependencies={"B"},
            )
        )

        workflow_config = {
            "actions": [
                {"name": "A", "depends_on": ["source"]},
                {"name": "B", "depends_on": ["A"]},
                {
                    "name": "C",
                    "depends_on": ["B"],
                    "context_scope": {"observe": ["A.field_x"]},
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        warnings = analyzer._check_lineage_reachability()
        assert len(warnings) == 0
