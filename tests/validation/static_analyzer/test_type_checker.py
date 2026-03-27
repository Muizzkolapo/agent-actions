"""Tests for the static type checker."""

from agent_actions.validation.static_analyzer import (
    ActionKind,
    DataFlowGraph,
    DataFlowNode,
    InputRequirement,
    OutputSchema,
    StaticTypeChecker,
)


class TestStaticTypeChecker:
    """Tests for StaticTypeChecker class."""

    def _create_graph_with_agents(self, agents_config):
        """Helper to create a graph with specified agents.

        Args:
            agents_config: List of dicts with keys:
                - name: agent name
                - fields: set of output fields
                - deps: set of dependency names
                - refs: list of (agent, field) tuples for requirements
        """
        graph = DataFlowGraph()

        # Add source node
        graph.add_node(
            DataFlowNode(
                name="source",
                agent_kind=ActionKind.SOURCE,
                output_schema=OutputSchema(is_dynamic=True),
            )
        )

        # Add agents
        for agent in agents_config:
            reqs = []
            for ref_agent, ref_field in agent.get("refs", []):
                reqs.append(
                    InputRequirement(
                        source_agent=ref_agent,
                        field_path=ref_field,
                        location="prompt",
                        raw_reference=f"{{{{ action.{ref_agent}.{ref_field} }}}}",
                    )
                )

            graph.add_node(
                DataFlowNode(
                    name=agent["name"],
                    agent_kind=agent.get("kind", ActionKind.LLM),
                    output_schema=OutputSchema(
                        schema_fields=agent.get("fields", set()),
                        is_schemaless=agent.get("schemaless", False),
                        is_dynamic=agent.get("dynamic", False),
                        dropped_fields=agent.get("dropped", set()),
                    ),
                    dependencies=agent.get("deps", set()),
                    input_requirements=reqs,
                )
            )

        graph.build_edges_from_requirements()
        return graph

    def test_valid_workflow(self):
        """Test checker passes for valid workflow."""
        graph = self._create_graph_with_agents(
            [
                {"name": "extractor", "fields": {"text", "metadata"}},
                {
                    "name": "summarizer",
                    "fields": {"summary"},
                    "deps": {"extractor"},
                    "refs": [("extractor", "text")],
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert result.is_valid
        assert len(result.errors) == 0

    def test_missing_agent_error(self):
        """Test error when referencing non-existent agent."""
        graph = self._create_graph_with_agents(
            [
                {
                    "name": "agent1",
                    "fields": {"result"},
                    "deps": {"nonexistent"},
                    "refs": [("nonexistent", "field")],
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert not result.is_valid
        assert len(result.errors) == 1
        assert "nonexistent" in result.errors[0].message
        assert "does not exist" in result.errors[0].message

    def test_implicit_dependency_is_invalid(self):
        """Test that references require reachable dependencies."""
        graph = self._create_graph_with_agents(
            [
                {"name": "upstream", "fields": {"data"}},
                {
                    "name": "downstream",
                    "fields": {"result"},
                    "deps": set(),  # No explicit dependency, but references upstream
                    "refs": [("upstream", "data")],
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert not result.is_valid
        assert len(result.errors) == 1
        assert "not reachable" in result.errors[0].message

    def test_reachable_via_ancestor_dependency(self):
        """Test reachability via dependency ancestors."""
        graph = self._create_graph_with_agents(
            [
                {"name": "upstream", "fields": {"data"}},
                {"name": "midstream", "fields": {"mid"}, "deps": {"upstream"}},
                {
                    "name": "downstream",
                    "fields": {"result"},
                    "deps": {"midstream"},
                    "refs": [("upstream", "data")],
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert result.is_valid
        assert len(result.errors) == 0

    def test_missing_field_error(self):
        """Test error when referencing non-existent field."""
        graph = self._create_graph_with_agents(
            [
                {"name": "extractor", "fields": {"text", "metadata"}},
                {
                    "name": "summarizer",
                    "fields": {"summary"},
                    "deps": {"extractor"},
                    "refs": [("extractor", "nonexistent_field")],
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert not result.is_valid
        assert len(result.errors) == 1
        assert "nonexistent_field" in result.errors[0].message
        assert "not found" in result.errors[0].message

    def test_dropped_field_error(self):
        """Test error when referencing dropped field."""
        graph = self._create_graph_with_agents(
            [
                {
                    "name": "extractor",
                    "fields": {"text", "metadata"},
                    "dropped": {"metadata"},
                },
                {
                    "name": "summarizer",
                    "fields": {"summary"},
                    "deps": {"extractor"},
                    "refs": [("extractor", "metadata")],  # Dropped field!
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert not result.is_valid
        assert len(result.errors) == 1
        assert "dropped" in result.errors[0].message.lower()

    def test_schemaless_agent_warning(self):
        """Test warning when referencing schemaless agent."""
        graph = self._create_graph_with_agents(
            [
                {"name": "extractor", "schemaless": True},
                {
                    "name": "summarizer",
                    "fields": {"summary"},
                    "deps": {"extractor"},
                    "refs": [("extractor", "text")],
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        # Should be valid (warning, not error)
        assert result.is_valid
        assert len(result.warnings) >= 1
        assert any("no schema" in w.message for w in result.warnings)

    def test_dynamic_schema_warning(self):
        """Test warning when referencing agent with dynamic schema."""
        graph = self._create_graph_with_agents(
            [
                {"name": "extractor", "dynamic": True},
                {
                    "name": "summarizer",
                    "fields": {"summary"},
                    "deps": {"extractor"},
                    "refs": [("extractor", "anything")],
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        # Should be valid (warning, not error)
        assert result.is_valid
        assert len(result.warnings) >= 1
        assert any("dynamic" in w.message for w in result.warnings)

    def test_unused_dependency_warning(self):
        """Test warning for declared but unused dependency."""
        graph = self._create_graph_with_agents(
            [
                {"name": "agent1", "fields": {"data"}},
                {"name": "agent2", "fields": {"other"}},
                {
                    "name": "consumer",
                    "fields": {"result"},
                    "deps": {"agent1", "agent2"},  # Both declared
                    "refs": [("agent1", "data")],  # Only agent1 used
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        _result = checker.check_all()
        warnings = checker.check_unused_dependencies()

        assert len(warnings) >= 1
        assert any("agent2" in w.message for w in warnings)
        assert any("never referenced" in w.message for w in warnings)

    def test_multiple_errors_collected(self):
        """Test multiple errors are all collected."""
        graph = self._create_graph_with_agents(
            [
                {"name": "extractor", "fields": {"text"}},
                {
                    "name": "agent1",
                    "fields": {"result"},
                    "refs": [("nonexistent", "field")],  # Error 1: missing agent
                },
                {
                    "name": "agent2",
                    "fields": {"result"},
                    "deps": {"extractor"},
                    "refs": [("extractor", "missing_field")],  # Error 2: missing field
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert not result.is_valid
        assert len(result.errors) >= 2

    def test_similar_field_suggestion(self):
        """Test hint suggests similar field names."""
        graph = self._create_graph_with_agents(
            [
                {"name": "extractor", "fields": {"summary", "summaries", "summarize"}},
                {
                    "name": "consumer",
                    "fields": {"result"},
                    "deps": {"extractor"},
                    "refs": [("extractor", "sumary")],  # Typo!
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert not result.is_valid
        # Should suggest similar fields
        assert any("summary" in str(e.hint) or "summar" in str(e.hint) for e in result.errors)

    def test_nested_field_path_validates_root(self):
        """Test nested paths like 'metadata.score' validate root field."""
        graph = self._create_graph_with_agents(
            [
                {"name": "analyzer", "fields": {"metadata", "text"}},
                {
                    "name": "consumer",
                    "fields": {"result"},
                    "deps": {"analyzer"},
                    "refs": [("analyzer", "metadata.score")],  # Nested path
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        # Should pass - 'metadata' exists as root field
        assert result.is_valid

    def test_error_location_tracking(self):
        """Test error includes location information."""
        graph = self._create_graph_with_agents(
            [
                {"name": "extractor", "fields": {"text"}},
                {
                    "name": "consumer",
                    "fields": {"result"},
                    "deps": {"extractor"},
                    "refs": [("extractor", "missing")],
                },
            ]
        )

        checker = StaticTypeChecker(graph)
        result = checker.check_all()

        assert len(result.errors) == 1
        error = result.errors[0]
        assert error.location.agent_name == "consumer"
        assert error.location.config_field == "prompt"
