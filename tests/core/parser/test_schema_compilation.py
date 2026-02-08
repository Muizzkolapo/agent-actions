"""
Tests for schema compilation during the render step.

These tests verify that:
1. Named schemas are inlined from schema/ directory
2. Inline schemas are expanded to unified format
3. Strict mode raises errors on schema load failures
"""

import pytest
import tempfile
import os
from pathlib import Path

import yaml

from agent_actions.prompt.render_workflow import (
    _load_named_schema,
    _expand_inline_schema,
    _is_inline_schema_dict,
    _compile_action_schemas,
    _compile_workflow_schemas,
)
from agent_actions.errors import ConfigurationError


class TestLoadNamedSchema:
    """Tests for _load_named_schema function."""

    def test_load_existing_schema(self, tmp_path):
        """Test loading an existing schema file."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        schema_content = {
            "name": "test_schema",
            "fields": [
                {"id": "field1", "type": "string"},
                {"id": "field2", "type": "number"},
            ],
        }

        schema_file = schema_dir / "test_schema.yml"
        with open(schema_file, "w") as f:
            yaml.dump(schema_content, f)

        result = _load_named_schema("test_schema", schema_dir)

        assert result["name"] == "test_schema"
        assert len(result["fields"]) == 2

    def test_load_missing_schema_raises_error(self, tmp_path):
        """Test that loading a missing schema raises ConfigurationError."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        with pytest.raises(ConfigurationError) as exc_info:
            _load_named_schema("nonexistent_schema", schema_dir)

        assert "not found" in str(exc_info.value)


class TestExpandInlineSchema:
    """Tests for _expand_inline_schema function."""

    def test_expand_simple_fields(self):
        """Test expanding simple field types."""
        inline_schema = {
            "name": "string",
            "age": "integer",
            "score": "number",
        }

        result = _expand_inline_schema(inline_schema)

        assert result["name"] == "InlineSchema"
        assert len(result["fields"]) == 3

        # Check fields are correctly converted
        field_ids = {f["id"] for f in result["fields"]}
        assert field_ids == {"name", "age", "score"}

    def test_expand_required_marker(self):
        """Test that '!' required marker is handled correctly."""
        inline_schema = {
            "required_field": "string!",
            "optional_field": "string",
        }

        result = _expand_inline_schema(inline_schema)

        required_field = next(f for f in result["fields"] if f["id"] == "required_field")
        optional_field = next(f for f in result["fields"] if f["id"] == "optional_field")

        assert required_field["required"] is True
        assert required_field["type"] == "string"  # '!' should be stripped
        assert optional_field["required"] is False

    def test_expand_array_type(self):
        """Test expanding array[type] format."""
        inline_schema = {
            "tags": "array[string]",
            "scores": "array[number]",
        }

        result = _expand_inline_schema(inline_schema)

        tags_field = next(f for f in result["fields"] if f["id"] == "tags")
        scores_field = next(f for f in result["fields"] if f["id"] == "scores")

        assert tags_field["type"] == "array"
        assert tags_field["items"]["type"] == "string"
        assert scores_field["type"] == "array"
        assert scores_field["items"]["type"] == "number"

    def test_expand_plain_array_type(self):
        """Test expanding plain 'array' type defaults to string items."""
        inline_schema = {"items": "array"}

        result = _expand_inline_schema(inline_schema)

        items_field = next(f for f in result["fields"] if f["id"] == "items")
        assert items_field["type"] == "array"
        assert items_field["items"]["type"] == "string"


class TestIsInlineSchemaDict:
    """Tests for _is_inline_schema_dict function."""

    @pytest.mark.parametrize(
        "schema,expected",
        [
            pytest.param({"field1": "string", "field2": "number"}, True, id="inline_schema"),
            pytest.param(
                {"name": "TestSchema", "fields": [{"id": "field1", "type": "string"}]},
                False,
                id="unified_format",
            ),
            pytest.param({}, False, id="empty_dict"),
            pytest.param({"field1": ["string", "null"]}, False, id="non_string_values"),
            pytest.param({"field1": "invalid_type"}, False, id="invalid_types"),
            pytest.param({"tags": "array[string]", "count": "integer"}, True, id="array_types"),
        ],
    )
    def test_inline_schema_detection(self, schema, expected):
        """Test detection of inline schema format."""
        assert _is_inline_schema_dict(schema) is expected


class TestCompileActionSchemas:
    """Tests for _compile_action_schemas function."""

    def test_inline_named_schema(self, tmp_path):
        """Test that schema_name references are inlined."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        schema_content = {
            "name": "my_schema",
            "fields": [{"id": "result", "type": "string"}],
        }
        schema_file = schema_dir / "my_schema.yml"
        with open(schema_file, "w") as f:
            yaml.dump(schema_content, f)

        action = {
            "name": "test_action",
            "schema_name": "my_schema",
        }

        _compile_action_schemas(action, schema_dir)

        # schema_name should be replaced with inlined schema
        assert "schema_name" not in action
        assert "schema" in action
        assert action["schema"]["name"] == "my_schema"

    def test_inline_schema_reference(self, tmp_path):
        """Test that schema: 'name' string references are inlined."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        schema_content = {
            "name": "ref_schema",
            "fields": [{"id": "data", "type": "object"}],
        }
        schema_file = schema_dir / "ref_schema.yml"
        with open(schema_file, "w") as f:
            yaml.dump(schema_content, f)

        action = {
            "name": "test_action",
            "schema": "ref_schema",
        }

        _compile_action_schemas(action, schema_dir)

        assert action["schema"]["name"] == "ref_schema"
        assert action["schema"]["fields"][0]["id"] == "data"

    def test_expand_inline_dict(self, tmp_path):
        """Test that inline dict schemas are expanded."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        action = {
            "name": "test_action",
            "schema": {
                "result": "string",
                "count": "integer!",
            },
        }

        _compile_action_schemas(action, schema_dir)

        # Should be expanded to unified format
        assert action["schema"]["name"] == "InlineSchema"
        assert "fields" in action["schema"]
        assert len(action["schema"]["fields"]) == 2


class TestCompileWorkflowSchemasStrict:
    """Tests for strict mode in _compile_workflow_schemas."""

    def test_strict_mode_raises_on_missing_schema(self, tmp_path):
        """Test that strict mode raises error on missing schema."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        data = {
            "actions": [
                {
                    "name": "action1",
                    "schema": "nonexistent_schema",
                }
            ]
        }

        with pytest.raises(ConfigurationError) as exc_info:
            _compile_workflow_schemas(data, schema_dir, strict=True)

        assert "Schema compilation failed" in str(exc_info.value)
        assert "error(s)" in str(exc_info.value)

    def test_strict_mode_collects_multiple_errors(self, tmp_path):
        """Test that strict mode collects all errors."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        data = {
            "actions": [
                {"name": "action1", "schema": "missing1"},
                {"name": "action2", "schema": "missing2"},
            ]
        }

        with pytest.raises(ConfigurationError) as exc_info:
            _compile_workflow_schemas(data, schema_dir, strict=True)

        # Should contain error count
        assert "2 error(s)" in str(exc_info.value)

    def test_non_strict_mode_logs_warning(self, tmp_path, caplog):
        """Test that non-strict mode logs warnings instead of raising."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        data = {
            "actions": [
                {"name": "action1", "schema": "missing_schema"},
            ]
        }

        # Should not raise
        _compile_workflow_schemas(data, schema_dir, strict=False)

        # Schema should remain as string (not inlined)
        assert data["actions"][0]["schema"] == "missing_schema"


class TestSchemaUtilsShared:
    """Tests for shared schema_utils module."""

    @pytest.mark.parametrize(
        "schema,expected",
        [
            pytest.param({"name": "foo", "fields": []}, True, id="fields_based"),
            pytest.param({"type": "object", "properties": {}}, True, id="json_schema_object"),
            pytest.param({"type": "array", "items": {}}, True, id="json_schema_array"),
            pytest.param({"field1": "string"}, False, id="inline_shorthand"),
            pytest.param("schema_name", False, id="non_dict"),
        ],
    )
    def test_is_compiled_schema(self, schema, expected):
        """Test is_compiled_schema detection."""
        from agent_actions.utils.schema_utils import is_compiled_schema

        assert is_compiled_schema(schema) is expected

    @pytest.mark.parametrize(
        "schema,expected",
        [
            pytest.param({"field1": "string", "field2": "number"}, True, id="basic_shorthand"),
            pytest.param({"required": "string!"}, True, id="required_marker"),
            pytest.param({"tags": "array[string]"}, True, id="array_type"),
            pytest.param({"name": "foo", "fields": []}, False, id="compiled_format"),
            pytest.param("schema_name", False, id="non_dict"),
        ],
    )
    def test_is_inline_schema_shorthand(self, schema, expected):
        """Test is_inline_schema_shorthand detection."""
        from agent_actions.utils.schema_utils import is_inline_schema_shorthand

        assert is_inline_schema_shorthand(schema) is expected
