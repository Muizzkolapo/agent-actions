"""Unit tests for unified_to_json_schema converter."""

import pytest
from agent_actions.utilities.udf_management.type_conversion import unified_to_json_schema


class TestUnifiedToJsonSchema:
    """Test unified schema to JSON Schema conversion."""

    def test_simple_schema_conversion(self):
        """Convert simple unified schema to JSON Schema."""
        unified = {
            "name": "TestInput",
            "fields": [
                {"id": "name", "type": "string", "required": True},
                {"id": "age", "type": "integer", "required": False},
            ],
        }

        result = unified_to_json_schema(unified)

        assert result["type"] == "object"
        assert result["properties"]["name"]["type"] == "string"
        assert result["properties"]["age"]["type"] == "integer"
        assert result["required"] == ["name"]
        assert result["additionalProperties"] is False

    def test_all_optional_fields(self):
        """Convert schema with all optional fields."""
        unified = {
            "name": "AllOptional",
            "fields": [
                {"id": "field1", "type": "string", "required": False},
                {"id": "field2", "type": "integer", "required": False},
            ],
        }

        result = unified_to_json_schema(unified)

        assert "required" not in result or result["required"] == []

    def test_array_field_preservation(self):
        """Array field items should be preserved."""
        unified = {
            "name": "WithArray",
            "fields": [
                {"id": "tags", "type": "array", "required": True, "items": {"type": "string"}}
            ],
        }

        result = unified_to_json_schema(unified)

        assert result["properties"]["tags"]["type"] == "array"
        assert result["properties"]["tags"]["items"]["type"] == "string"

    def test_additional_properties_always_false(self):
        """JSON Schema should always set additionalProperties to false."""
        unified = {"name": "Test", "fields": [{"id": "field", "type": "string", "required": True}]}

        result = unified_to_json_schema(unified)

        assert result["additionalProperties"] is False
