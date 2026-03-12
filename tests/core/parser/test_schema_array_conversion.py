"""
Tests for array-type JSON schema conversion to unified format.

These tests verify that array schemas (JSON Schema format with type='array')
are properly converted to the unified format and compile correctly for all vendors.
"""

from agent_actions.output.response.schema import (
    _convert_json_schema_to_unified,
    compile_unified_schema,
)


class TestArraySchemaConversion:
    """Test array-type schema conversion to unified format."""

    def test_array_schema_with_object_items(self):
        """Array with object items should convert properly."""
        schema = {
            "name": "facts",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": {"type": "string"}, "source": {"type": "string"}},
                "required": ["fact"],
            },
        }

        result = compile_unified_schema(schema, "anthropic")

        # Verify properties are not empty
        assert result[0]["input_schema"]["properties"], "Properties should not be empty"
        assert "facts" in result[0]["input_schema"]["properties"], "Should have 'facts' property"

        # Verify structure
        facts_prop = result[0]["input_schema"]["properties"]["facts"]
        assert facts_prop["type"] == "array", "Property should be array type"
        assert facts_prop["items"]["type"] == "object", "Items should be object type"
        assert "fact" in facts_prop["items"]["properties"], "Should have 'fact' in items"
        assert "source" in facts_prop["items"]["properties"], "Should have 'source' in items"

    def test_array_schema_with_primitive_items_string(self):
        """Array with primitive string items should work."""
        schema = {"name": "tags", "type": "array", "items": {"type": "string"}}

        result = compile_unified_schema(schema, "openai")

        # Should not crash and should have properties
        assert result["schema"]["properties"], "Properties should not be empty"
        assert "tags" in result["schema"]["properties"], "Should have 'tags' property"

        # Verify items are preserved as primitives
        tags_prop = result["schema"]["properties"]["tags"]
        assert tags_prop["type"] == "array", "Property should be array type"
        assert tags_prop["items"]["type"] == "string", "Items should be string type"

    def test_array_schema_with_primitive_items_number(self):
        """Array with primitive number items should work."""
        schema = {"name": "scores", "type": "array", "items": {"type": "number"}}

        result = compile_unified_schema(schema, "ollama")

        assert result["properties"], "Properties should not be empty"
        assert "scores" in result["properties"], "Should have 'scores' property"

        scores_prop = result["properties"]["scores"]
        assert scores_prop["type"] == "array", "Property should be array type"
        assert scores_prop["items"]["type"] == "number", "Items should be number type"

    def test_array_schema_without_items(self):
        """Array without items key doesn't trigger conversion (no 'items' in schema check)."""
        schema = {
            "name": "broken",
            "type": "array",
            # Missing 'items' key - won't trigger array conversion
        }

        # This won't trigger conversion because detection checks 'items' in unified
        # It will be treated as a malformed unified schema with no fields
        result = compile_unified_schema(schema, "openai")

        # Should not crash - will compile with empty properties
        assert result is not None, "Should return a result, not crash"
        # Empty properties because no 'fields' and conversion not triggered
        assert result["schema"]["properties"] == {}, "Should have empty properties"

    def test_unified_format_not_converted(self):
        """Unified format should bypass conversion."""
        schema = {
            "name": "standard",
            "fields": [{"id": "field1", "type": "string", "required": True}],
        }

        result = compile_unified_schema(schema, "anthropic")

        # Should have 'field1' not 'standard'
        assert "field1" in result[0]["input_schema"]["properties"], (
            "Should have field1 from fields array"
        )
        assert "standard" not in result[0]["input_schema"]["properties"], (
            "Should not wrap in schema name for unified format"
        )

    def test_array_schema_with_description(self):
        """Array schema description should be preserved."""
        schema = {
            "name": "items",
            "description": "List of items",
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}}},
        }

        result = compile_unified_schema(schema, "anthropic")

        assert result[0]["description"] == "List of items", "Description should be preserved"

    def test_array_schema_with_nested_properties(self):
        """Array schema with nested object properties should work."""
        schema = {
            "name": "users",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {
                        "type": "object",
                        "properties": {"street": {"type": "string"}, "city": {"type": "string"}},
                    },
                },
                "required": ["name"],
            },
        }

        result = compile_unified_schema(schema, "openai")

        users_prop = result["schema"]["properties"]["users"]
        assert "address" in users_prop["items"]["properties"], (
            "Nested properties should be preserved"
        )
        assert users_prop["items"]["properties"]["address"]["type"] == "object", (
            "Nested object type should be preserved"
        )

    def test_array_schema_all_vendors(self):
        """Array schema should compile for all vendors."""
        schema = {
            "name": "data",
            "type": "array",
            "items": {"type": "object", "properties": {"value": {"type": "string"}}},
        }

        vendors = ["openai", "anthropic", "gemini", "ollama"]

        for vendor in vendors:
            result = compile_unified_schema(schema, vendor)
            assert result is not None, f"Should compile for {vendor}"

            # Check vendor-specific structure
            if vendor == "anthropic":
                assert isinstance(result, list), f"{vendor} should return list"
                assert result[0]["input_schema"]["properties"], f"{vendor} should have properties"
            elif vendor == "openai":
                assert "schema" in result, f"{vendor} should have schema key"
                assert result["schema"]["properties"], f"{vendor} should have properties"
            elif vendor == "gemini":
                assert "schema" in result, f"{vendor} should have schema key"
            elif vendor == "ollama":
                assert result["properties"], f"{vendor} should have properties"

    def test_array_schema_optional_required_flag(self):
        """Array schema with required flag should be respected."""
        # Test with required=False
        schema_optional = {
            "name": "optional_array",
            "type": "array",
            "required": False,
            "items": {"type": "string"},
        }

        result = compile_unified_schema(schema_optional, "openai")

        # Check that array is not in required list
        assert "optional_array" not in result["schema"].get("required", []), (
            "Optional array should not be in required list"
        )

    def test_array_schema_with_item_constraints(self):
        """Array schema with item-level constraints should preserve them."""
        schema = {
            "name": "validated_items",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "pattern": "^[a-zA-Z0-9+_.-]+@[a-zA-Z0-9.-]+$"},
                    "age": {"type": "integer", "minimum": 0, "maximum": 150},
                },
            },
        }

        result = compile_unified_schema(schema, "anthropic")

        items_props = result[0]["input_schema"]["properties"]["validated_items"]["items"][
            "properties"
        ]

        # Check constraints are preserved
        assert "pattern" in items_props["email"], "Pattern constraint should be preserved"
        # Note: minimum/maximum might not be in compile_field output depending on implementation


class TestConversionFunction:
    """Test the _convert_json_schema_to_unified function directly."""

    def test_convert_basic_array_schema(self):
        """Test basic conversion logic."""
        schema = {
            "name": "test",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"field": {"type": "string"}},
                "required": ["field"],
            },
        }

        result = _convert_json_schema_to_unified(schema)

        assert "fields" in result, "Should have fields key"
        assert len(result["fields"]) == 1, "Should have one field"
        assert result["fields"][0]["id"] == "test", "Field id should match schema name"
        assert result["fields"][0]["type"] == "array", "Field should be array type"

    def test_convert_preserves_name_and_description(self):
        """Conversion should preserve name and description."""
        schema = {
            "name": "my_schema",
            "description": "My description",
            "type": "array",
            "items": {"type": "string"},
        }

        result = _convert_json_schema_to_unified(schema)

        assert result["name"] == "my_schema", "Name should be preserved"
        assert result["description"] == "My description", "Description should be preserved"

    def test_convert_defaults_missing_name(self):
        """Conversion should default missing name to 'response'."""
        schema = {"type": "array", "items": {"type": "string"}}

        result = _convert_json_schema_to_unified(schema)

        assert result["name"] == "response", "Should default to 'response'"
        assert result["fields"][0]["id"] == "response", "Field id should match default name"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_schema_with_both_fields_and_type_array(self):
        """Schema with both 'fields' and 'type: array' should prefer fields (not convert)."""
        schema = {
            "name": "mixed",
            "type": "array",
            "fields": [{"id": "field1", "type": "string", "required": True}],
            "items": {"type": "object", "properties": {"ignored": {"type": "string"}}},
        }

        result = compile_unified_schema(schema, "anthropic")

        # Should use fields, not convert array
        assert "field1" in result[0]["input_schema"]["properties"], "Should use fields array"
        assert "mixed" not in result[0]["input_schema"]["properties"], (
            "Should not wrap in schema name"
        )

    def test_array_schema_with_minItems_maxItems(self):
        """Array schema with minItems/maxItems should preserve them if supported."""
        schema = {
            "name": "bounded_array",
            "type": "array",
            "minItems": 1,
            "maxItems": 10,
            "items": {"type": "string"},
        }

        # Should not crash
        result = compile_unified_schema(schema, "openai")
        assert result is not None, "Should compile successfully"

    def test_empty_string_items_type(self):
        """Items with empty string type should be handled."""
        schema = {
            "name": "test",
            "type": "array",
            "items": {"type": ""},  # Empty type string
        }

        # Should default to object handling
        result = compile_unified_schema(schema, "anthropic")
        assert result is not None, "Should handle gracefully"
