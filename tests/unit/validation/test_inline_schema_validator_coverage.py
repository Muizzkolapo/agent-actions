"""Tests for InlineSchemaValidator to improve coverage."""

import pytest

from agent_actions.validation.action_validators.inline_schema_validator import (
    InlineSchemaValidator,
)
from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationContext,
)


@pytest.fixture
def validator():
    """Create an InlineSchemaValidator instance."""
    return InlineSchemaValidator()


def _make_context(entry: dict, agent_name: str = "test_agent") -> ActionEntryValidationContext:
    """Helper to build a validation context from an entry dict."""
    return ActionEntryValidationContext(entry=entry, agent_name_context=agent_name)


# ---------------------------------------------------------------------------
# No schema key present
# ---------------------------------------------------------------------------


class TestNoSchemaKey:
    """When 'schema' is absent, validator should pass immediately."""

    def test_no_schema_key(self, validator):
        ctx = _make_context({"prompt": "hello"})
        result = validator.validate(ctx)
        assert result.errors == []
        assert result.warnings == []

    def test_empty_entry(self, validator):
        ctx = _make_context({})
        result = validator.validate(ctx)
        assert result.errors == []


# ---------------------------------------------------------------------------
# Non-dict schema
# ---------------------------------------------------------------------------


class TestNonDictSchema:
    """When 'schema' is not a dict, should error."""

    def test_string_schema(self, validator):
        ctx = _make_context({"schema": "string_value"})
        result = validator.validate(ctx)
        assert len(result.errors) == 1
        assert "must be a dictionary" in result.errors[0]

    def test_list_schema(self, validator):
        ctx = _make_context({"schema": ["a", "b"]})
        result = validator.validate(ctx)
        assert len(result.errors) == 1

    def test_int_schema(self, validator):
        ctx = _make_context({"schema": 42})
        result = validator.validate(ctx)
        assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# Compiled (unified) schema
# ---------------------------------------------------------------------------


class TestCompiledSchema:
    """When schema is in compiled format, it should pass through."""

    def test_fields_based_compiled_schema(self, validator):
        ctx = _make_context(
            {"schema": {"fields": [{"name": "x", "type": "string"}]}}
        )
        result = validator.validate(ctx)
        assert result.errors == []

    def test_json_schema_object_format(self, validator):
        ctx = _make_context(
            {
                "schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            }
        )
        result = validator.validate(ctx)
        assert result.errors == []

    def test_json_schema_array_format(self, validator):
        ctx = _make_context(
            {
                "schema": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            }
        )
        result = validator.validate(ctx)
        assert result.errors == []

    def test_compiled_schema_with_schema_name_warns(self, validator):
        ctx = _make_context(
            {
                "schema": {"fields": [{"name": "x", "type": "string"}]},
                "schema_name": "output_schema",
            }
        )
        result = validator.validate(ctx)
        assert result.errors == []
        assert len(result.warnings) == 1
        assert "take precedence" in result.warnings[0]


# ---------------------------------------------------------------------------
# Inline shorthand schema - valid types
# ---------------------------------------------------------------------------


class TestValidInlineSchemaTypes:
    """Test valid shorthand type specifications."""

    @pytest.mark.parametrize(
        "field_type",
        ["string", "number", "integer", "boolean", "array", "object"],
    )
    def test_basic_types(self, validator, field_type):
        ctx = _make_context({"schema": {"field1": field_type}})
        result = validator.validate(ctx)
        assert result.errors == [], f"Failed for type '{field_type}': {result.errors}"

    @pytest.mark.parametrize(
        "field_type",
        ["string!", "number!", "integer!", "boolean!"],
    )
    def test_required_marker_types(self, validator, field_type):
        ctx = _make_context({"schema": {"field1": field_type}})
        result = validator.validate(ctx)
        assert result.errors == [], f"Failed for type '{field_type}': {result.errors}"

    @pytest.mark.parametrize(
        "field_type",
        [
            "array[string]",
            "array[number]",
            "array[integer]",
            "array[boolean]",
            "array[object]",
        ],
    )
    def test_array_types(self, validator, field_type):
        ctx = _make_context({"schema": {"field1": field_type}})
        result = validator.validate(ctx)
        assert result.errors == [], f"Failed for type '{field_type}': {result.errors}"

    def test_multiple_valid_fields(self, validator):
        ctx = _make_context(
            {
                "schema": {
                    "name": "string!",
                    "age": "integer",
                    "tags": "array[string]",
                    "active": "boolean",
                }
            }
        )
        result = validator.validate(ctx)
        assert result.errors == []


# ---------------------------------------------------------------------------
# Inline shorthand schema - invalid types
# ---------------------------------------------------------------------------


class TestInvalidInlineSchemaTypes:
    """Test invalid shorthand type specifications."""

    def test_invalid_type_name(self, validator):
        ctx = _make_context({"schema": {"field1": "datetime"}})
        result = validator.validate(ctx)
        assert len(result.errors) == 1
        assert "invalid type" in result.errors[0].lower()

    def test_non_string_field_type_value(self, validator):
        ctx = _make_context({"schema": {"field1": 123}})
        result = validator.validate(ctx)
        assert len(result.errors) == 1
        assert "must be a string type" in result.errors[0]

    def test_mixed_valid_and_invalid(self, validator):
        ctx = _make_context(
            {
                "schema": {
                    "name": "string",
                    "data": "blob",
                }
            }
        )
        result = validator.validate(ctx)
        assert len(result.errors) == 1
        assert "blob" in result.errors[0] or "invalid type" in result.errors[0].lower()


# ---------------------------------------------------------------------------
# Complex array[object:...] types
# ---------------------------------------------------------------------------


class TestComplexArrayObjectType:
    """Test array[object:{...}] notation in inline schemas."""

    def test_valid_complex_type_json(self, validator):
        ctx = _make_context(
            {"schema": {"items": 'array[object:{"name": "string", "value": "number"}]'}}
        )
        result = validator.validate(ctx)
        assert result.errors == []

    def test_valid_complex_type_python_literal(self, validator):
        ctx = _make_context(
            {"schema": {"items": "array[object:{'name': 'string'}]"}}
        )
        result = validator.validate(ctx)
        assert result.errors == []

    def test_invalid_complex_type_bad_json(self, validator):
        ctx = _make_context(
            {"schema": {"items": "array[object:not_valid_json]"}}
        )
        result = validator.validate(ctx)
        assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# schema + schema_name warning
# ---------------------------------------------------------------------------


class TestSchemaNameConflictWarning:
    """When both schema and schema_name are present, warn."""

    def test_inline_with_schema_name(self, validator):
        ctx = _make_context(
            {
                "schema": {"name": "string"},
                "schema_name": "output_schema",
            }
        )
        result = validator.validate(ctx)
        assert result.errors == []
        assert len(result.warnings) == 1
        assert "take precedence" in result.warnings[0]

    def test_inline_without_schema_name_no_warning(self, validator):
        ctx = _make_context({"schema": {"name": "string"}})
        result = validator.validate(ctx)
        assert result.warnings == []


# ---------------------------------------------------------------------------
# Case-insensitive key handling
# ---------------------------------------------------------------------------


class TestCaseInsensitiveKeys:
    """Verify that entry keys are normalized to lowercase."""

    def test_uppercase_schema_key(self, validator):
        ctx = _make_context({"Schema": {"name": "string"}})
        result = validator.validate(ctx)
        assert result.errors == []

    def test_uppercase_schema_name_key(self, validator):
        ctx = _make_context(
            {"Schema": {"name": "string"}, "Schema_Name": "my_schema"}
        )
        result = validator.validate(ctx)
        assert len(result.warnings) == 1
