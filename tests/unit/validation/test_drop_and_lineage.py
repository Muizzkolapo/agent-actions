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
        """Build a graph with source -> upstream -> downstream."""
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
        graph.add_node(
            DataFlowNode(
                name="downstream",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields=set()),
                dependencies={"upstream"},
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

        errors, _warnings = analyzer._check_drop_directives()
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

        errors, _warnings = analyzer._check_drop_directives()
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

        errors, _warnings = analyzer._check_drop_directives()
        assert len(errors) == 1
        msg = errors[0].message.lower()
        assert "non-existent" in msg or "nonexistent" in msg
        assert errors[0].available_fields  # Should have available fields

    def test_drop_with_wildcard_no_error(self):
        """Drop with wildcard on a dependency expands and produces no error."""
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

        # Expansion must run first — wildcards are resolved before checks.
        expansion_errors = analyzer._expand_wildcards()
        assert len(expansion_errors) == 0

        errors, _warnings = analyzer._check_drop_directives()
        assert len(errors) == 0

        # Verify the wildcard was expanded to concrete fields.
        drop_refs = workflow_config["actions"][0]["context_scope"]["drop"]
        assert "upstream.*" not in drop_refs
        assert "upstream.summary" in drop_refs

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

        errors, _warnings = analyzer._check_drop_directives()
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

        errors, _warnings = analyzer._check_drop_directives()
        assert len(errors) == 0

    def test_drop_on_unreachable_namespace_warns(self):
        """Drop on a namespace not in the dependency chain produces a warning."""
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
                name="action_a",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"field_x"}),
                dependencies={"source"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="action_b",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"result"}),
                dependencies={"source"},
            )
        )
        workflow_config = {
            "actions": [
                {
                    "name": "action_b",
                    "depends_on": ["source"],
                    "context_scope": {
                        "drop": ["action_a.field_x"],
                    },
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        errors, warnings = analyzer._check_drop_directives()
        assert len(errors) == 0
        assert len(warnings) == 1
        assert "not in its dependency chain" in warnings[0].message
        assert "action_a" in warnings[0].message
        assert "action_b" in warnings[0].message

    def test_drop_on_unreachable_namespace_deduplicates(self):
        """Multiple drops on the same unreachable namespace produce one warning."""
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
                name="unreachable",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"f1", "f2", "f3"}),
                dependencies={"source"},
            )
        )
        graph.add_node(
            DataFlowNode(
                name="consumer",
                agent_kind=ActionKind.LLM,
                output_schema=OutputSchema(schema_fields={"out"}),
                dependencies={"source"},
            )
        )
        workflow_config = {
            "actions": [
                {
                    "name": "consumer",
                    "depends_on": ["source"],
                    "context_scope": {
                        "drop": ["unreachable.f1", "unreachable.f2", "unreachable.f3"],
                    },
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(workflow_config, graph)

        errors, warnings = analyzer._check_drop_directives()
        assert len(errors) == 0
        assert len(warnings) == 1  # One warning, not three


class TestExpandWildcards:
    """Tests for _expand_wildcards() — wildcard-as-field-expansion compiler pass."""

    def _make_graph(self, nodes):
        """Build a graph from a list of (name, kind, output_schema, deps) tuples."""
        graph = DataFlowGraph()
        for name, kind, output, deps in nodes:
            graph.add_node(
                DataFlowNode(
                    name=name,
                    agent_kind=kind,
                    output_schema=output,
                    dependencies=deps,
                )
            )
        return graph

    def test_known_schema_expanded(self):
        """Wildcard on action with known schema expands to concrete fields."""
        graph = self._make_graph(
            [
                ("source", ActionKind.SOURCE, OutputSchema(is_dynamic=True), set()),
                ("A", ActionKind.LLM, OutputSchema(schema_fields={"x", "y"}), {"source"}),
            ]
        )
        config = {
            "actions": [{"name": "B", "context_scope": {"observe": ["A.*"]}}],
        }
        analyzer = _build_analyzer_with_graph(config, graph)
        errors = analyzer._expand_wildcards()

        assert len(errors) == 0
        refs = config["actions"][0]["context_scope"]["observe"]
        assert "A.*" not in refs
        assert sorted(refs) == ["A.x", "A.y"]

    def test_dynamic_schema_left_as_wildcard(self):
        """Wildcard on dynamic schema is left unexpanded."""
        graph = self._make_graph(
            [
                ("source", ActionKind.SOURCE, OutputSchema(is_dynamic=True), set()),
                ("A", ActionKind.LLM, OutputSchema(is_dynamic=True), {"source"}),
            ]
        )
        config = {
            "actions": [{"name": "B", "context_scope": {"drop": ["A.*"]}}],
        }
        analyzer = _build_analyzer_with_graph(config, graph)
        errors = analyzer._expand_wildcards()

        assert len(errors) == 0
        assert config["actions"][0]["context_scope"]["drop"] == ["A.*"]

    def test_schemaless_resolves_to_nothing(self):
        """Wildcard on schemaless action resolves to empty (no fields to expand)."""
        graph = self._make_graph(
            [
                ("source", ActionKind.SOURCE, OutputSchema(is_dynamic=True), set()),
                ("A", ActionKind.LLM, OutputSchema(is_schemaless=True), {"source"}),
            ]
        )
        config = {
            "actions": [{"name": "B", "context_scope": {"passthrough": ["A.*"]}}],
        }
        analyzer = _build_analyzer_with_graph(config, graph)
        errors = analyzer._expand_wildcards()

        assert len(errors) == 0
        assert config["actions"][0]["context_scope"]["passthrough"] == []

    def test_unknown_action_errors(self):
        """Wildcard on non-existent action produces an error."""
        graph = self._make_graph(
            [
                ("source", ActionKind.SOURCE, OutputSchema(is_dynamic=True), set()),
            ]
        )
        config = {
            "actions": [{"name": "B", "context_scope": {"drop": ["nonexistent.*"]}}],
        }
        analyzer = _build_analyzer_with_graph(config, graph)
        errors = analyzer._expand_wildcards()

        assert len(errors) == 1
        assert "unknown action" in errors[0].message.lower()
        assert "nonexistent" in errors[0].message

    def test_special_namespace_not_expanded(self):
        """Wildcards on special namespaces (source, seed, etc.) are left as-is."""
        graph = self._make_graph(
            [
                ("source", ActionKind.SOURCE, OutputSchema(is_dynamic=True), set()),
            ]
        )
        config = {
            "actions": [{"name": "B", "context_scope": {"observe": ["source.*"]}}],
        }
        analyzer = _build_analyzer_with_graph(config, graph)
        errors = analyzer._expand_wildcards()

        assert len(errors) == 0
        assert config["actions"][0]["context_scope"]["observe"] == ["source.*"]

    def test_explicit_refs_untouched(self):
        """Non-wildcard references are not modified."""
        graph = self._make_graph(
            [
                ("source", ActionKind.SOURCE, OutputSchema(is_dynamic=True), set()),
                ("A", ActionKind.LLM, OutputSchema(schema_fields={"x", "y"}), {"source"}),
            ]
        )
        config = {
            "actions": [
                {"name": "B", "context_scope": {"observe": ["A.x"]}},
            ],
        }
        analyzer = _build_analyzer_with_graph(config, graph)
        errors = analyzer._expand_wildcards()

        assert len(errors) == 0
        assert config["actions"][0]["context_scope"]["observe"] == ["A.x"]

    def test_multiple_directives_expanded(self):
        """Wildcards in observe, drop, and passthrough are all expanded."""
        graph = self._make_graph(
            [
                ("source", ActionKind.SOURCE, OutputSchema(is_dynamic=True), set()),
                ("A", ActionKind.LLM, OutputSchema(schema_fields={"f1", "f2"}), {"source"}),
            ]
        )
        config = {
            "actions": [
                {
                    "name": "B",
                    "context_scope": {
                        "observe": ["A.*"],
                        "drop": ["A.*"],
                        "passthrough": ["A.*"],
                    },
                },
            ],
        }
        analyzer = _build_analyzer_with_graph(config, graph)
        errors = analyzer._expand_wildcards()

        assert len(errors) == 0
        for directive in ("observe", "drop", "passthrough"):
            refs = config["actions"][0]["context_scope"][directive]
            assert "A.*" not in refs
            assert sorted(refs) == ["A.f1", "A.f2"]

    def test_empty_schema_resolves_to_nothing(self):
        """Wildcard on known but empty schema resolves to empty list."""
        graph = self._make_graph(
            [
                ("source", ActionKind.SOURCE, OutputSchema(is_dynamic=True), set()),
                ("A", ActionKind.LLM, OutputSchema(schema_fields=set()), {"source"}),
            ]
        )
        config = {
            "actions": [{"name": "B", "context_scope": {"observe": ["A.*"]}}],
        }
        analyzer = _build_analyzer_with_graph(config, graph)
        errors = analyzer._expand_wildcards()

        assert len(errors) == 0
        assert config["actions"][0]["context_scope"]["observe"] == []

    def test_observe_fields_included_in_expansion(self):
        """Expansion includes both schema_fields and observe_fields."""
        graph = self._make_graph(
            [
                ("source", ActionKind.SOURCE, OutputSchema(is_dynamic=True), set()),
                (
                    "A",
                    ActionKind.LLM,
                    OutputSchema(schema_fields={"s1"}, observe_fields={"o1"}),
                    {"source"},
                ),
            ]
        )
        config = {
            "actions": [{"name": "B", "context_scope": {"observe": ["A.*"]}}],
        }
        analyzer = _build_analyzer_with_graph(config, graph)
        errors = analyzer._expand_wildcards()

        assert len(errors) == 0
        refs = sorted(config["actions"][0]["context_scope"]["observe"])
        assert refs == ["A.o1", "A.s1"]


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
