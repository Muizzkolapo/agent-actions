"""Unit tests for SchemaFieldValidator."""

from agent_actions.input.preprocessing.field_resolution.schema_field_validator import (
    SchemaFieldValidator,
)


class TestSchemaFieldValidator:
    """Test schema field validation logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.validator = SchemaFieldValidator()

    def test_validate_simple_field_exists(self):
        """Test validation of simple field that exists."""
        schema = {
            "type": "object",
            "properties": {"result": {"type": "string"}, "count": {"type": "integer"}},
            "required": ["result"],
        }

        result = self.validator.validate_field_path(
            field_path=["result"], json_schema=schema, action_name="my_action"
        )

        assert result.exists
        assert result.field_type == "string"
        assert result.action_name == "my_action"
        assert result.is_required
        assert result.error is None

    def test_validate_simple_field_not_found(self):
        """Test validation of non-existent field."""
        schema = {"type": "object", "properties": {"result": {"type": "string"}}}

        result = self.validator.validate_field_path(
            field_path=["invalid"], json_schema=schema, action_name="my_action"
        )

        assert not result.exists
        assert result.error is not None
        assert "invalid" in result.error
        assert "my_action" in result.error
        assert "Available fields: result" in result.error

    def test_validate_nested_field_exists(self):
        """Test validation of nested field path."""
        schema = {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}, "status": {"type": "string"}},
                }
            },
        }

        result = self.validator.validate_field_path(
            field_path=["data", "count"], json_schema=schema, action_name="my_action"
        )

        assert result.exists
        assert result.field_type == "integer"
        assert result.error is None

    def test_validate_deeply_nested_field(self):
        """Test validation of deeply nested field path."""
        schema = {
            "type": "object",
            "properties": {
                "response": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "object",
                            "properties": {
                                "metrics": {
                                    "type": "object",
                                    "properties": {"count": {"type": "integer"}},
                                }
                            },
                        }
                    },
                }
            },
        }

        result = self.validator.validate_field_path(
            field_path=["response", "data", "metrics", "count"],
            json_schema=schema,
            action_name="my_action",
        )

        assert result.exists
        assert result.field_type == "integer"

    def test_validate_nested_field_not_found(self):
        """Test validation of non-existent nested field."""
        schema = {
            "type": "object",
            "properties": {
                "data": {"type": "object", "properties": {"count": {"type": "integer"}}}
            },
        }

        result = self.validator.validate_field_path(
            field_path=["data", "invalid"], json_schema=schema, action_name="my_action"
        )

        assert not result.exists
        assert result.error is not None
        assert "data.invalid" in result.error

    def test_validate_optional_field(self):
        """Test handling of optional fields (not in required)."""
        schema = {
            "type": "object",
            "properties": {
                "required_field": {"type": "string"},
                "optional_field": {"type": "string"},
            },
            "required": ["required_field"],
        }

        # Required field
        result_required = self.validator.validate_field_path(
            field_path=["required_field"], json_schema=schema, action_name="my_action"
        )

        assert result_required.exists
        assert result_required.is_required

        # Optional field
        result_optional = self.validator.validate_field_path(
            field_path=["optional_field"], json_schema=schema, action_name="my_action"
        )

        assert result_optional.exists
        assert not result_optional.is_required

    def test_validate_array_field(self):
        """Test validation of array fields."""
        schema = {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"type": "string"}}},
        }

        result = self.validator.validate_field_path(
            field_path=["items"], json_schema=schema, action_name="my_action"
        )

        assert result.exists
        assert result.field_type == "array"

    def test_type_extraction(self):
        """Test correct extraction of field types from schema."""
        schema = {
            "type": "object",
            "properties": {
                "string_field": {"type": "string"},
                "int_field": {"type": "integer"},
                "number_field": {"type": "number"},
                "bool_field": {"type": "boolean"},
                "array_field": {"type": "array"},
                "object_field": {"type": "object"},
            },
        }

        types_to_test = [
            ("string_field", "string"),
            ("int_field", "integer"),
            ("number_field", "number"),
            ("bool_field", "boolean"),
            ("array_field", "array"),
            ("object_field", "object"),
        ]

        for field_name, expected_type in types_to_test:
            result = self.validator.validate_field_path(
                field_path=[field_name], json_schema=schema, action_name="my_action"
            )

            assert result.exists
            assert result.field_type == expected_type, (
                f"Expected {expected_type}, got {result.field_type}"
            )

    def test_empty_field_path(self):
        """Test handling of empty field path."""
        schema = {"type": "object", "properties": {"field": {"type": "string"}}}

        result = self.validator.validate_field_path(
            field_path=[], json_schema=schema, action_name="my_action"
        )

        assert not result.exists
        assert result.error is not None
        assert "Empty field path" in result.error

    def test_validate_non_object_schema(self):
        """Test validation against non-object schema."""
        schema = {
            "type": "string"  # Not an object
        }

        result = self.validator.validate_field_path(
            field_path=["field"], json_schema=schema, action_name="my_action"
        )

        assert not result.exists
