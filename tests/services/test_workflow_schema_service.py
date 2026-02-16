"""Tests for the WorkflowSchemaService."""

import pytest

from agent_actions.models.action_schema import ActionKind, ActionSchema, FieldSource
from agent_actions.workflow.schema_service import WorkflowSchemaService


class TestWorkflowSchemaService:
    """Tests for WorkflowSchemaService class."""

    def _create_service(self, actions):
        """Helper to create a service with given actions.

        Args:
            actions: List of action config dicts

        Returns:
            WorkflowSchemaService instance
        """
        workflow_config = {
            "name": "test_workflow",
            "actions": actions,
        }
        return WorkflowSchemaService(workflow_config)

    def test_get_action_schema_returns_none_for_missing(self):
        """Test get_action_schema returns None for non-existent action."""
        service = self._create_service([{"name": "action1", "model_vendor": "openai"}])

        schema = service.get_action_schema("nonexistent")
        assert schema is None

    def test_get_action_schema_caches_result(self):
        """Test get_action_schema caches the result."""
        service = self._create_service([{"name": "action1", "model_vendor": "openai"}])

        schema1 = service.get_action_schema("action1")
        schema2 = service.get_action_schema("action1")

        assert schema1 is schema2  # Same object

    def test_get_all_schemas_returns_all_actions(self):
        """Test get_all_schemas returns all action schemas."""
        service = self._create_service(
            [
                {"name": "action1", "model_vendor": "openai"},
                {"name": "action2", "kind": "tool", "function_name": "my_tool"},
            ]
        )

        schemas = service.get_all_schemas()

        assert len(schemas) == 2
        assert "action1" in schemas
        assert "action2" in schemas
        assert isinstance(schemas["action1"], ActionSchema)
        assert isinstance(schemas["action2"], ActionSchema)

    def test_validate_detects_missing_field(self):
        """Test validate detects missing field references."""
        service = self._create_service(
            [
                {
                    "name": "extractor",
                    "model_vendor": "openai",
                    "schema": {"text": "str"},
                },
                {
                    "name": "consumer",
                    "model_vendor": "openai",
                    "depends_on": ["extractor"],
                    "prompt": "{{ action.extractor.nonexistent }}",
                },
            ]
        )

        result = service.validate()

        assert not result.is_valid
        assert len(result.errors) >= 1
        assert any("nonexistent" in str(e.message) for e in result.errors)

    def test_get_execution_order_returns_list(self):
        """Test get_execution_order returns action names in order."""
        service = self._create_service(
            [
                {"name": "first", "model_vendor": "openai"},
                {
                    "name": "second",
                    "model_vendor": "openai",
                    "depends_on": ["first"],
                },
            ]
        )

        order = service.get_execution_order()

        assert isinstance(order, list)
        # source should be excluded
        assert "source" not in order
        # first should come before second
        assert order.index("first") < order.index("second")

    def test_get_downstream_actions(self):
        """Test get_downstream_actions returns dependents."""
        service = self._create_service(
            [
                {"name": "producer", "model_vendor": "openai"},
                {
                    "name": "consumer1",
                    "model_vendor": "openai",
                    "depends_on": ["producer"],
                },
                {
                    "name": "consumer2",
                    "model_vendor": "openai",
                    "depends_on": ["producer"],
                },
            ]
        )

        downstream = service.get_downstream_actions("producer")

        assert sorted(downstream) == ["consumer1", "consumer2"]

    def test_get_downstream_actions_empty(self):
        """Test get_downstream_actions returns empty for leaf action."""
        service = self._create_service(
            [
                {"name": "producer", "model_vendor": "openai"},
                {
                    "name": "consumer",
                    "model_vendor": "openai",
                    "depends_on": ["producer"],
                },
            ]
        )

        downstream = service.get_downstream_actions("consumer")

        assert downstream == []

    def test_workflow_name(self):
        """Test workflow_name property."""
        config = {
            "name": "my_workflow",
            "actions": [{"name": "action1", "model_vendor": "openai"}],
        }
        service = WorkflowSchemaService(config)

        assert service.workflow_name == "my_workflow"

    def test_action_schema_includes_output_fields(self):
        """Test action schema correctly includes output fields."""
        service = self._create_service(
            [
                {
                    "name": "extractor",
                    "model_vendor": "openai",
                    "schema": {"summary": "str", "facts": "list[str]"},
                }
            ]
        )

        schema = service.get_action_schema("extractor")

        # Should have output fields
        output_names = [f.name for f in schema.output_fields]
        assert "summary" in output_names
        assert "facts" in output_names

        # All should be SCHEMA source
        for f in schema.output_fields:
            assert f.source == FieldSource.SCHEMA

    def test_action_schema_includes_upstream_refs(self):
        """Test action schema correctly includes upstream references."""
        service = self._create_service(
            [
                {
                    "name": "extractor",
                    "model_vendor": "openai",
                    "schema": {"text": "str"},
                },
                {
                    "name": "consumer",
                    "model_vendor": "openai",
                    "depends_on": ["extractor"],
                    "prompt": "Process: {{ action.extractor.text }}",
                },
            ]
        )

        schema = service.get_action_schema("consumer")

        assert len(schema.upstream_refs) >= 1
        ref = schema.upstream_refs[0]
        assert ref.source_agent == "extractor"
        assert ref.field_name == "text"

    def test_hitl_action_schema_preserves_hitl_kind(self):
        """Test HITL action is classified as HITL kind with canonical output fields."""
        service = self._create_service(
            [
                {
                    "name": "review",
                    "kind": "hitl",
                    "model_vendor": "hitl",
                }
            ]
        )

        schema = service.get_action_schema("review")

        assert schema.kind == ActionKind.HITL
        # Canonical HITL fields from HITL_OUTPUT_JSON_SCHEMA
        assert "hitl_status" in schema.available_outputs
        assert "user_comment" in schema.available_outputs
        assert "timestamp" in schema.available_outputs

    def test_action_schema_includes_dependencies(self):
        """Test action schema includes declared dependencies."""
        service = self._create_service(
            [
                {"name": "upstream", "model_vendor": "openai"},
                {
                    "name": "downstream",
                    "model_vendor": "openai",
                    "depends_on": ["upstream"],
                },
            ]
        )

        schema = service.get_action_schema("downstream")

        assert "upstream" in schema.dependencies

    def test_action_schema_includes_downstream(self):
        """Test action schema includes downstream actions."""
        service = self._create_service(
            [
                {"name": "producer", "model_vendor": "openai"},
                {
                    "name": "consumer",
                    "model_vendor": "openai",
                    "depends_on": ["producer"],
                },
            ]
        )

        schema = service.get_action_schema("producer")

        assert "consumer" in schema.downstream
