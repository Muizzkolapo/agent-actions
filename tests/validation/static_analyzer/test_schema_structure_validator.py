"""Unit tests for schema_structure_validator module."""

import pytest

from agent_actions.validation.static_analyzer.schema_structure_validator import (
    SchemaStructureValidator,
)


class TestSchemaStructureValidator:
    """Tests for SchemaStructureValidator class."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return SchemaStructureValidator()

    class TestUnifiedFormat:
        """Tests for unified schema format validation."""

        @pytest.fixture
        def validator(self):
            return SchemaStructureValidator()

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

        def test_empty_fields_list(self, validator):
            """Test empty fields list is rejected."""
            schema = {"name": "test_schema", "fields": []}
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "empty" in errors[0].message.lower()

        def test_fields_not_list(self, validator):
            """Test fields must be a list."""
            schema = {"name": "test_schema", "fields": "not a list"}
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "list" in errors[0].message.lower()

        def test_field_missing_id(self, validator):
            """Test field without id is rejected."""
            schema = {
                "name": "test_schema",
                "fields": [{"type": "string"}],
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "id" in errors[0].message.lower() or "name" in errors[0].message.lower()

        def test_field_missing_type(self, validator):
            """Test field without type is rejected."""
            schema = {
                "name": "test_schema",
                "fields": [{"id": "name"}],
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "type" in errors[0].message.lower()

        def test_field_invalid_type(self, validator):
            """Test field with invalid type is rejected."""
            schema = {
                "name": "test_schema",
                "fields": [{"id": "name", "type": "invalid_type"}],
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "invalid" in errors[0].message.lower()

        def test_duplicate_field_ids(self, validator):
            """Test duplicate field ids are rejected."""
            schema = {
                "name": "test_schema",
                "fields": [
                    {"id": "name", "type": "string"},
                    {"id": "name", "type": "string"},  # Duplicate
                ],
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "duplicate" in errors[0].message.lower()

        def test_array_field_without_items(self, validator):
            """Test array field without items is rejected."""
            schema = {
                "name": "test_schema",
                "fields": [{"id": "items", "type": "array"}],
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "items" in errors[0].message.lower()

        def test_array_field_with_valid_items(self, validator):
            """Test array field with valid items passes."""
            schema = {
                "name": "test_schema",
                "fields": [
                    {
                        "id": "items",
                        "type": "array",
                        "items": {"type": "string"},
                    }
                ],
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 0

        def test_array_object_items_without_properties(self, validator):
            """Test array with object items but no properties is rejected."""
            schema = {
                "name": "test_schema",
                "fields": [
                    {
                        "id": "items",
                        "type": "array",
                        "items": {"type": "object"},
                    }
                ],
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "properties" in errors[0].message.lower()

    class TestJsonSchemaFormat:
        """Tests for JSON Schema format validation."""

        @pytest.fixture
        def validator(self):
            return SchemaStructureValidator()

        def test_valid_object_schema(self, validator):
            """Test valid object schema passes validation."""
            schema = {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name"],
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 0

        def test_object_schema_empty_properties(self, validator):
            """Test object schema with empty properties is rejected."""
            schema = {
                "type": "object",
                "properties": {},
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "empty" in errors[0].message.lower()

        def test_valid_array_schema(self, validator):
            """Test valid array schema passes validation."""
            schema = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                    },
                },
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 0

        def test_array_schema_missing_items(self, validator):
            """Test array schema without items is rejected."""
            schema = {"type": "array"}
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "items" in errors[0].message.lower()

        def test_array_schema_invalid_items(self, validator):
            """Test array schema with invalid items is rejected."""
            schema = {"type": "array", "items": "not a dict"}
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "items" in errors[0].message.lower()

        def test_required_field_not_in_properties(self, validator):
            """Test required field not in properties is rejected."""
            schema = {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name", "missing_field"],
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "missing_field" in errors[0].message

        def test_property_missing_type(self, validator):
            """Test property without type is rejected."""
            schema = {
                "type": "object",
                "properties": {
                    "name": {},  # Missing type
                },
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "type" in errors[0].message.lower()

        def test_property_invalid_type(self, validator):
            """Test property with invalid type is rejected."""
            schema = {
                "type": "object",
                "properties": {
                    "name": {"type": "invalid"},
                },
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "invalid" in errors[0].message.lower()

    class TestInlineShorthandFormat:
        """Tests for inline shorthand format validation."""

        @pytest.fixture
        def validator(self):
            return SchemaStructureValidator()

        def test_valid_inline_schema(self, validator):
            """Test valid inline shorthand schema passes validation."""
            schema = {
                "name": "string!",
                "age": "number",
                "active": "boolean",
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 0

        def test_invalid_type_in_inline(self, validator):
            """Test invalid type in inline schema is rejected."""
            schema = {
                "name": "invalid_type",
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "invalid" in errors[0].message.lower()

        def test_array_shorthand(self, validator):
            """Test array shorthand format is valid."""
            schema = {
                "items": "array[string]",
                "numbers": "array[number]",
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 0

        def test_invalid_array_item_type(self, validator):
            """Test invalid array item type is rejected."""
            schema = {
                "items": "array[invalid]",
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "invalid" in errors[0].message.lower()

        def test_non_string_type_value(self, validator):
            """Test non-string type value is rejected."""
            schema = {
                "name": 123,  # Should be string
            }
            errors = validator.validate_schema(schema, "test_action")
            assert len(errors) == 1
            assert "string" in errors[0].message.lower()

    class TestSchemaCompilability:
        """Tests for schema compilability validation."""

        @pytest.fixture
        def validator(self):
            return SchemaStructureValidator()

        def test_valid_schema_compiles(self, validator):
            """Test valid schema compiles without errors."""
            schema = {
                "name": "test_schema",
                "fields": [{"id": "name", "type": "string", "required": True}],
            }
            errors = validator.validate_schema_compilability(
                schema, "test_action", "openai"
            )
            assert len(errors) == 0

        def test_empty_schema_skipped(self, validator):
            """Test empty schema is skipped."""
            errors = validator.validate_schema_compilability({}, "test_action", "openai")
            assert len(errors) == 0

        def test_none_schema_skipped(self, validator):
            """Test None schema is skipped."""
            errors = validator.validate_schema_compilability(
                None, "test_action", "openai"
            )
            assert len(errors) == 0
