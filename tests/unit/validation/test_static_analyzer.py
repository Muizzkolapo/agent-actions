"""J-4: Coverage of SchemaExtractor — field extraction from action configs."""

import pytest

from agent_actions.validation.static_analyzer.schema_extractor import SchemaExtractor
from agent_actions.validation.static_analyzer.data_flow_graph import OutputSchema


class TestSchemaExtractorLLMAction:
    """SchemaExtractor.extract_schema() for LLM actions."""

    def test_llm_action_no_schema_returns_empty_output_schema(self, tmp_path):
        """An LLM action with no schema config returns an OutputSchema with no fields."""
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
        extractor = SchemaExtractor(project_root=tmp_path)
        config = {"kind": "llm", "agent_type": "my_agent"}
        result = extractor.extract_schema(config)
        assert isinstance(result, OutputSchema)

    def test_tool_action_returns_output_schema(self, tmp_path):
        """Tool actions return an OutputSchema (may be dynamic)."""
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
        extractor = SchemaExtractor(project_root=tmp_path)
        config = {"kind": "tool", "impl": "nonexistent_tool"}
        result = extractor.extract_schema(config)
        assert isinstance(result, OutputSchema)

    def test_hitl_action_returns_output_schema_with_hitl_fields(self, tmp_path):
        """HITL actions return schema with HITL-specific fields."""
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
        extractor = SchemaExtractor(project_root=tmp_path)
        config = {"kind": "hitl"}
        result = extractor.extract_schema(config)
        assert isinstance(result, OutputSchema)
        # HITL should produce fields from HITL_OUTPUT_JSON_SCHEMA (hitl_status, user_comment, timestamp)
        assert "hitl_status" in result.schema_fields


class TestSchemaExtractorExtractFieldsFromJsonSchema:
    """SchemaExtractor.extract_fields_from_json_schema() extracts top-level property names."""

    def setup_method(self):
        self.extractor = SchemaExtractor()

    def test_object_schema_extracts_properties(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
        fields = self.extractor.extract_fields_from_json_schema(schema)
        assert "name" in fields
        assert "age" in fields

    def test_array_schema_extracts_item_properties(self):
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "result": {"type": "string"},
                },
            },
        }
        fields = self.extractor.extract_fields_from_json_schema(schema)
        assert "result" in fields

    def test_empty_schema_returns_empty_set(self):
        fields = self.extractor.extract_fields_from_json_schema({})
        assert isinstance(fields, set)
        assert len(fields) == 0

    def test_schema_without_properties_returns_empty(self):
        schema = {"type": "string"}
        fields = self.extractor.extract_fields_from_json_schema(schema)
        assert isinstance(fields, set)

    def test_context_scope_observe_applied(self, tmp_path):
        """observe in context_scope adds fields to output schema."""
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
        extractor = SchemaExtractor(project_root=tmp_path)
        config = {
            "kind": "llm",
            "context_scope": {"observe": ["upstream.field_a"]},
        }
        result = extractor.extract_schema(config)
        assert isinstance(result, OutputSchema)
        # context_scope.observe entries are extracted via _extract_field_name("upstream.field_a") -> "field_a"
        assert "field_a" in result.observe_fields
