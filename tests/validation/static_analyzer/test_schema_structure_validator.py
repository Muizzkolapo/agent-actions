"""Unit tests for schema_structure_validator module."""

import pytest

from agent_actions.validation.static_analyzer.schema_structure_validator import (
    SchemaStructureValidator,
)


@pytest.fixture
def validator():
    """Create validator instance."""
    return SchemaStructureValidator()


class TestUnifiedFormat:
    """Tests for unified schema format validation."""

    def test_valid_unified_schema(self, validator):
        """Test valid unified schema passes validation."""
        schema = {
            "name": "test_schema",
            "fields": [
                {"id": "name", "type": "string", "required": True},
                {"id": "age", "type": "number"},
            ],
        }
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 0

    @pytest.mark.parametrize(
        "schema,error_pattern",
        [
            pytest.param(
                {"name": "test_schema", "fields": []},
                "empty",
                id="empty_fields",
            ),
            pytest.param(
                {"name": "test_schema", "fields": "not a list"},
                "list",
                id="fields_not_list",
            ),
            pytest.param(
                {"name": "test_schema", "fields": [{"type": "string"}]},
                "id",
                id="field_missing_id",
            ),
            pytest.param(
                {"name": "test_schema", "fields": [{"id": "name"}]},
                "type",
                id="field_missing_type",
            ),
            pytest.param(
                {"name": "test_schema", "fields": [{"id": "name", "type": "invalid_type"}]},
                "invalid",
                id="field_invalid_type",
            ),
            pytest.param(
                {
                    "name": "test_schema",
                    "fields": [{"id": "name", "type": "string"}, {"id": "name", "type": "string"}],
                },
                "duplicate",
                id="duplicate_field_ids",
            ),
            pytest.param(
                {"name": "test_schema", "fields": [{"id": "items", "type": "array"}]},
                "items",
                id="array_without_items",
            ),
        ],
    )
    def test_unified_validation_errors(self, validator, schema, error_pattern):
        """Test various validation errors in unified format."""
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 1
        assert error_pattern in errors[0].message.lower()

    def test_array_field_with_valid_items(self, validator):
        """Test array field with valid items passes."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "items", "type": "array", "items": {"type": "string"}}],
        }
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 0

    def test_array_object_items_without_properties(self, validator):
        """Test array with object items but no properties is rejected."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "items", "type": "array", "items": {"type": "object"}}],
        }
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 1
        assert "properties" in errors[0].message.lower()


class TestJsonSchemaFormat:
    """Tests for JSON Schema format validation."""

    def test_valid_object_schema(self, validator):
        """Test valid object schema passes validation."""
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
        }
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 0

    @pytest.mark.parametrize(
        "schema,error_pattern",
        [
            pytest.param(
                {"type": "object", "properties": {}},
                "empty",
                id="empty_properties",
            ),
            pytest.param(
                {"type": "array"},
                "items",
                id="array_missing_items",
            ),
            pytest.param(
                {"type": "array", "items": "not a dict"},
                "items",
                id="array_invalid_items",
            ),
            pytest.param(
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name", "missing_field"],
                },
                "missing_field",
                id="required_not_in_properties",
            ),
            pytest.param(
                {"type": "object", "properties": {"name": {}}},
                "type",
                id="property_missing_type",
            ),
            pytest.param(
                {"type": "object", "properties": {"name": {"type": "invalid"}}},
                "invalid",
                id="property_invalid_type",
            ),
        ],
    )
    def test_json_schema_validation_errors(self, validator, schema, error_pattern):
        """Test various validation errors in JSON Schema format."""
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 1
        assert error_pattern in errors[0].message.lower()

    def test_valid_array_schema(self, validator):
        """Test valid array schema passes validation."""
        schema = {
            "type": "array",
            "items": {"type": "object", "properties": {"id": {"type": "string"}}},
        }
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 0


class TestInlineShorthandFormat:
    """Tests for inline shorthand format validation."""

    def test_valid_inline_schema(self, validator):
        """Test valid inline shorthand schema passes validation."""
        schema = {"name": "string!", "age": "number", "active": "boolean"}
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 0

    @pytest.mark.parametrize(
        "schema,error_pattern",
        [
            pytest.param({"name": "invalid_type"}, "invalid", id="invalid_type"),
            pytest.param({"items": "array[invalid]"}, "invalid", id="invalid_array_item_type"),
            pytest.param({"name": 123}, "string", id="non_string_type_value"),
        ],
    )
    def test_inline_validation_errors(self, validator, schema, error_pattern):
        """Test various validation errors in inline shorthand format."""
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 1
        assert error_pattern in errors[0].message.lower()

    def test_array_shorthand(self, validator):
        """Test array shorthand format is valid."""
        schema = {"items": "array[string]", "numbers": "array[number]"}
        errors = validator.validate_schema(schema, "test_action")
        assert len(errors) == 0


class TestSchemaCompilability:
    """Tests for schema compilability validation."""

    def test_valid_schema_compiles(self, validator):
        """Test valid schema compiles without errors."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        errors = validator.validate_schema_compilability(schema, "test_action", "openai")
        assert len(errors) == 0

    def test_empty_schema_skipped(self, validator):
        """Test empty schema is skipped."""
        errors = validator.validate_schema_compilability({}, "test_action", "openai")
        assert len(errors) == 0

    def test_none_schema_skipped(self, validator):
        """Test None schema is skipped."""
        errors = validator.validate_schema_compilability(None, "test_action", "openai")
        assert len(errors) == 0
