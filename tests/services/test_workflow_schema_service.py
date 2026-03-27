"""Tests for the WorkflowSchemaService."""

from pathlib import Path
from unittest.mock import patch

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


class TestExtractFieldMetadata:
    """Tests for WorkflowSchemaService._extract_field_metadata."""

    _extract = staticmethod(WorkflowSchemaService._extract_field_metadata)

    # -- None / empty schema --------------------------------------------------

    def test_none_schema_returns_defaults(self):
        ft, desc, req = self._extract(None, "any_field")
        assert ft == "unknown"
        assert desc == ""
        assert req is False

    def test_empty_schema_returns_defaults(self):
        ft, desc, req = self._extract({}, "any_field")
        assert ft == "unknown"
        assert desc == ""
        assert req is False

    # -- Format 1: Custom 'fields' array --------------------------------------

    def test_format1_exact_match(self):
        schema = {
            "fields": [
                {"id": "name", "type": "string", "description": "Full name", "required": True},
                {"id": "age", "type": "integer", "description": "Age in years"},
            ]
        }
        ft, desc, req = self._extract(schema, "name")
        assert ft == "string"
        assert desc == "Full name"
        assert req is True

    def test_format1_defaults_required_false(self):
        schema = {
            "fields": [
                {"id": "age", "type": "integer", "description": "Age in years"},
            ]
        }
        ft, desc, req = self._extract(schema, "age")
        assert ft == "integer"
        assert desc == "Age in years"
        assert req is False

    def test_format1_field_not_found(self):
        schema = {"fields": [{"id": "name", "type": "string"}]}
        ft, desc, req = self._extract(schema, "missing")
        assert ft == "unknown"
        assert desc == ""
        assert req is False

    def test_format1_name_key_matches(self):
        """Fields using 'name' instead of 'id' should be found."""
        schema = {
            "fields": [
                {"name": "title", "type": "string", "description": "Title field"},
            ]
        }
        ft, desc, req = self._extract(schema, "title")
        assert ft == "string"
        assert desc == "Title field"
        assert req is False

    def test_format1_non_dict_items_skipped(self):
        """Non-dict items in the fields array should be skipped, not raise."""
        schema = {
            "fields": [
                "just_a_string",
                42,
                {"id": "valid", "type": "boolean", "description": "A flag"},
            ]
        }
        ft, desc, req = self._extract(schema, "valid")
        assert ft == "boolean"
        assert desc == "A flag"
        assert req is False

    def test_format1_id_takes_precedence_over_name(self):
        """When both 'id' and 'name' are present, 'id' is used (via or short-circuit)."""
        schema = {
            "fields": [
                {"id": "real_id", "name": "alt_name", "type": "string", "description": "Test"},
            ]
        }
        ft, desc, req = self._extract(schema, "real_id")
        assert ft == "string"
        # 'alt_name' should NOT match
        ft2, desc2, req2 = self._extract(schema, "alt_name")
        assert ft2 == "unknown"

    def test_format1_array_field_with_items_properties(self):
        schema = {
            "fields": [
                {
                    "id": "items",
                    "type": "array",
                    "items": {
                        "properties": {
                            "sku": {"type": "string", "description": "Product SKU"},
                        },
                        "required": ["sku"],
                    },
                }
            ]
        }
        ft, desc, req = self._extract(schema, "sku")
        assert ft == "string"
        assert desc == "Product SKU"
        assert req is True

    # -- Format 2: Array schema with items.properties --------------------------

    def test_format2_array_schema(self):
        schema = {
            "type": "array",
            "items": {
                "properties": {
                    "id": {"type": "integer", "description": "Record ID"},
                    "value": {"type": "number", "description": "Metric value"},
                },
                "required": ["id"],
            },
        }
        ft, desc, req = self._extract(schema, "id")
        assert ft == "integer"
        assert desc == "Record ID"
        assert req is True

    def test_format2_optional_field(self):
        schema = {
            "type": "array",
            "items": {
                "properties": {
                    "value": {"type": "number", "description": "Metric value"},
                },
                "required": [],
            },
        }
        ft, desc, req = self._extract(schema, "value")
        assert ft == "number"
        assert desc == "Metric value"
        assert req is False

    def test_format2_field_not_found(self):
        schema = {
            "type": "array",
            "items": {"properties": {"x": {"type": "string"}}, "required": []},
        }
        ft, desc, req = self._extract(schema, "missing")
        assert ft == "unknown"
        assert desc == ""
        assert req is False

    # -- Format 3: Object schema with properties -------------------------------

    def test_format3_object_schema(self):
        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Executive summary"},
                "score": {"type": "number", "description": "Quality score"},
            },
            "required": ["summary"],
        }
        ft, desc, req = self._extract(schema, "summary")
        assert ft == "string"
        assert desc == "Executive summary"
        assert req is True

    def test_format3_optional_field(self):
        schema = {
            "properties": {
                "score": {"type": "number", "description": "Quality score"},
            },
            "required": [],
        }
        ft, desc, req = self._extract(schema, "score")
        assert ft == "number"
        assert desc == "Quality score"
        assert req is False

    def test_format3_field_not_found(self):
        schema = {
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        }
        ft, desc, req = self._extract(schema, "missing")
        assert ft == "unknown"
        assert desc == ""
        assert req is False


class TestLookupInProperties:
    """Tests for WorkflowSchemaService._lookup_in_properties."""

    _lookup = staticmethod(WorkflowSchemaService._lookup_in_properties)

    def test_found_required(self):
        props = {"name": {"type": "string", "description": "Name"}}
        result = self._lookup(props, ["name"], "name")
        assert result == ("string", "Name", True)

    def test_found_optional(self):
        props = {"name": {"type": "string", "description": "Name"}}
        result = self._lookup(props, [], "name")
        assert result == ("string", "Name", False)

    def test_not_found(self):
        props = {"name": {"type": "string"}}
        result = self._lookup(props, ["name"], "missing")
        assert result is None

    def test_missing_type_defaults_unknown(self):
        props = {"name": {"description": "Name"}}
        result = self._lookup(props, [], "name")
        assert result == ("unknown", "Name", False)

    def test_missing_description_defaults_empty(self):
        props = {"name": {"type": "string"}}
        result = self._lookup(props, [], "name")
        assert result == ("string", "", False)


class TestFromActionConfigs:
    """Tests for WorkflowSchemaService.from_action_configs factory."""

    SAMPLE_ACTIONS = {
        "extract": {"model_vendor": "openai", "schema": {"text": "str"}},
        "summarize": {"model_vendor": "openai", "depends_on": ["extract"]},
    }

    def test_returns_service_instance(self):
        service = WorkflowSchemaService.from_action_configs("wf", self.SAMPLE_ACTIONS)
        assert isinstance(service, WorkflowSchemaService)

    def test_sets_workflow_name(self):
        service = WorkflowSchemaService.from_action_configs("my_wf", self.SAMPLE_ACTIONS)
        assert service.workflow_name == "my_wf"

    def test_passes_project_root(self, tmp_path: Path):
        service = WorkflowSchemaService.from_action_configs(
            "wf", self.SAMPLE_ACTIONS, project_root=tmp_path
        )
        # project_root is forwarded to SchemaExtractor inside the analyzer
        assert service._analyzer.schema_extractor.project_root == tmp_path

    def test_without_udf_registry_defaults_empty(self):
        service = WorkflowSchemaService.from_action_configs("wf", self.SAMPLE_ACTIONS)
        # When with_udf_registry=False, SchemaExtractor gets empty dict
        assert service._analyzer.schema_extractor.udf_registry == {}

    def test_with_udf_registry_graceful_on_import_error(self):
        """ImportError when UDF registry unavailable → still constructs service."""
        with patch.dict("sys.modules", {"agent_actions.utils.udf_management.registry": None}):
            service = WorkflowSchemaService.from_action_configs(
                "wf", self.SAMPLE_ACTIONS, with_udf_registry=True
            )
            # Graceful fallback: udf_registry=None passed, extractor stores {}
            assert service._analyzer.schema_extractor.udf_registry == {}

    def test_builds_valid_workflow_config(self):
        service = WorkflowSchemaService.from_action_configs("wf", self.SAMPLE_ACTIONS)
        schemas = service.get_all_schemas()
        assert "extract" in schemas
        assert "summarize" in schemas

    def test_passes_tool_schemas(self):
        """Pre-scanned tool_schemas reach SchemaExtractor, skipping lazy scan."""
        fake_tools = {"my_func": {"name": "my_func", "input_schema": {}}}
        service = WorkflowSchemaService.from_action_configs(
            "wf", self.SAMPLE_ACTIONS, tool_schemas=fake_tools
        )
        extractor = service._analyzer.schema_extractor
        # Pre-populated — _get_tool_schemas returns injected data without scanning
        assert extractor._tool_schemas is fake_tools
        assert extractor._get_tool_schemas() is fake_tools

    def test_tool_schemas_none_preserves_lazy_load(self):
        """Omitting tool_schemas keeps lazy-load behavior (cache starts None)."""
        service = WorkflowSchemaService.from_action_configs("wf", self.SAMPLE_ACTIONS)
        assert service._analyzer.schema_extractor._tool_schemas is None

    def test_tool_schemas_empty_dict_skips_scan(self):
        """Empty dict is a valid pre-scan result — should not trigger lazy scan."""
        service = WorkflowSchemaService.from_action_configs(
            "wf", self.SAMPLE_ACTIONS, tool_schemas={}
        )
        extractor = service._analyzer.schema_extractor
        assert extractor._get_tool_schemas() == {}
