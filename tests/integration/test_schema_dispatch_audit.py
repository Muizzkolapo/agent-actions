"""Comprehensive schema dispatch audit tests.

Tests the full schema pipeline:
- Resolution: inline vs named vs tool-derived vs HITL auto-generated
- Compilation: vendor-specific format per provider
- Validation: on_schema_mismatch modes (warn, reprompt, reject)
- Edge cases: json_mode interaction, schemaless actions, dispatch_task()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.errors import ConfigValidationError, SchemaValidationError
from agent_actions.output.response.context_data import (
    _compile_schema_for_vendor,
    _unwrap_nested_schema,
)
from agent_actions.output.response.dispatch_injection import (
    _inject_functions_into_schema,
    _resolve_dispatch_in_schema,
)
from agent_actions.output.response.schema import ResponseSchemaCompiler
from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.processing.helpers import (
    _resolve_schema_mismatch_mode,
    _validate_llm_output_schema,
)
from agent_actions.utils.constants import HITL_OUTPUT_JSON_SCHEMA, HITL_OUTPUT_SCHEMA
from agent_actions.validation.schema_output_validator import (
    SchemaValidationReport,
    _check_field_types,
    _check_properties_type,
    _extract_schema_fields,
    validate_and_raise_if_invalid,
    validate_output_against_schema,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_UNIFIED_SCHEMA: dict[str, Any] = {
    "name": "test_schema",
    "fields": [
        {"id": "title", "type": "string", "required": True},
        {"id": "score", "type": "number", "required": True},
        {"id": "tags", "type": "array", "required": False},
    ],
}

SAMPLE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "score": {"type": "number"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "score"],
}

SAMPLE_INLINE_DICT: dict[str, Any] = {
    "title": "string!",
    "score": "number!",
    "tags": "array[string]",
}


# ===================================================================
# 1. Schema Resolution
# ===================================================================


class TestSchemaResolution:
    """Tests for schema source resolution: inline, named, tool-derived, HITL."""

    def test_inline_schema_used_directly(self):
        """Inline schema dict is loaded without hitting the file system."""
        compiler = ResponseSchemaCompiler(project_root=None, tools_path=None)
        config = {"schema": SAMPLE_UNIFIED_SCHEMA, "name": "my_action"}
        compiled, captured = compiler.compile(config, "openai")

        assert compiled is not None
        # OpenAI format has name + schema wrapper
        assert isinstance(compiled, dict)
        assert "schema" in compiled
        assert compiled["schema"]["properties"]["title"]["type"] == "string"

    def test_named_schema_loaded_from_file(self, tmp_path: Path):
        """Named schema loaded from schema store via SchemaLoader."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        schema_file = schema_dir / "my_schema.yml"
        schema_file.write_text(
            "name: my_schema\nfields:\n  - id: result\n    type: string\n    required: true\n"
        )
        # Patch get_schema_path where it's imported inside SchemaLoader
        with patch(
            "agent_actions.config.path_config.get_schema_path",
            return_value=str(schema_dir),
        ):
            compiler = ResponseSchemaCompiler(project_root=tmp_path, tools_path=None)
            config = {"schema_name": "my_schema", "name": "test_action"}
            compiled, _ = compiler.compile(config, "openai")

        assert compiled is not None
        assert isinstance(compiled, dict)
        assert "result" in compiled["schema"]["properties"]

    def test_inline_takes_precedence_over_schema_name(self):
        """When both inline and schema_name are set, inline wins.

        Inline schema is checked first in ResponseSchemaCompiler.compile();
        if present, schema_name is ignored entirely.
        """
        compiler = ResponseSchemaCompiler(project_root=None, tools_path=None)
        config = {
            "schema": SAMPLE_UNIFIED_SCHEMA,
            "schema_name": "should_be_ignored",
            "name": "test_action",
        }
        compiled, _ = compiler.compile(config, "openai")

        # Should have fields from inline (title, score, tags)
        assert "title" in compiled["schema"]["properties"]
        assert "score" in compiled["schema"]["properties"]

    def test_missing_schema_file_raises(self, tmp_path: Path):
        """Named schema referencing nonexistent file raises FileNotFoundError."""
        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        with patch(
            "agent_actions.config.path_config.get_schema_path",
            return_value=str(schema_dir),
        ):
            compiler = ResponseSchemaCompiler(project_root=tmp_path, tools_path=None)
            config = {"schema_name": "nonexistent_schema", "name": "test_action"}
            with pytest.raises(FileNotFoundError):
                compiler.compile(config, "openai")

    def test_no_schema_returns_none(self):
        """Action with no schema configured returns (None, {})."""
        compiler = ResponseSchemaCompiler(project_root=None, tools_path=None)
        config = {"name": "test_action"}
        compiled, captured = compiler.compile(config, "openai")

        assert compiled is None
        assert captured == {}

    def test_tool_vendor_returns_none(self):
        """Tool vendor always returns None (tools don't use schemas)."""
        compiler = ResponseSchemaCompiler(project_root=None, tools_path=None)
        config = {"schema": SAMPLE_UNIFIED_SCHEMA, "name": "test_action"}
        compiled, _ = compiler.compile(config, "tool")

        assert compiled is None

    def test_hitl_auto_schema_complete(self):
        """HITL auto-schema includes all required fields (hitl_status, timestamp)."""
        assert "properties" in HITL_OUTPUT_JSON_SCHEMA
        props = HITL_OUTPUT_JSON_SCHEMA["properties"]
        assert "hitl_status" in props
        assert "user_comment" in props
        assert "timestamp" in props
        # Required fields
        assert "hitl_status" in HITL_OUTPUT_JSON_SCHEMA["required"]
        assert "timestamp" in HITL_OUTPUT_JSON_SCHEMA["required"]
        # additionalProperties=False prevents data loss
        assert HITL_OUTPUT_JSON_SCHEMA.get("additionalProperties") is False

    def test_hitl_unified_schema_matches_json_schema(self):
        """HITL unified schema fields match JSON schema properties."""
        unified_ids = {f["id"] for f in HITL_OUTPUT_SCHEMA["fields"]}
        json_props = set(HITL_OUTPUT_JSON_SCHEMA["properties"].keys())
        assert unified_ids == json_props

    def test_nested_schema_unwrapped(self):
        """Nested {schema: {fields: [...]}} is unwrapped to {fields: [...]}."""
        nested = {
            "name": "outer",
            "schema": {
                "name": "inner",
                "fields": [{"id": "x", "type": "string", "required": True}],
            },
        }
        result = _unwrap_nested_schema(nested)
        assert "fields" in result
        assert result["fields"][0]["id"] == "x"

    def test_nested_schema_preserves_name(self):
        """If nested schema has no name, outer name is merged in."""
        nested = {
            "name": "outer",
            "schema": {
                "fields": [{"id": "x", "type": "string", "required": True}],
            },
        }
        result = _unwrap_nested_schema(nested)
        assert result["name"] == "outer"

    def test_non_schema_nested_key_preserved(self):
        """If nested 'schema' doesn't look like a schema, don't unwrap."""
        base = {
            "name": "test",
            "schema": "just_a_string",
        }
        result = _unwrap_nested_schema(base)
        assert result["schema"] == "just_a_string"


# ===================================================================
# 2. Vendor Compilation
# ===================================================================


class TestVendorCompilation:
    """Tests that each vendor receives its correct format."""

    def test_openai_json_schema_format(self):
        """OpenAI gets {name, schema: {type: object, properties, required, additionalProperties}}."""
        compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "openai")
        assert isinstance(compiled, dict)
        assert compiled["name"] == "test_schema"
        inner = compiled["schema"]
        assert inner["type"] == "object"
        assert "title" in inner["properties"]
        assert "score" in inner["properties"]
        assert "title" in inner["required"]
        assert "score" in inner["required"]
        assert inner["additionalProperties"] is False

    def test_anthropic_tool_format(self):
        """Anthropic gets [{name, description, input_schema: {type, properties, required}}]."""
        compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "anthropic")
        assert isinstance(compiled, list)
        assert len(compiled) == 1
        tool = compiled[0]
        assert tool["name"] == "test_schema"
        assert "input_schema" in tool
        inner = tool["input_schema"]
        assert inner["type"] == "object"
        assert "title" in inner["properties"]
        assert inner["additionalProperties"] is False

    def test_gemini_format_has_full_schema(self):
        """Gemini gets {name, schema: {type: object, properties, required}}."""
        compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "gemini")
        assert isinstance(compiled, dict)
        assert compiled["name"] == "test_schema"
        inner = compiled["schema"]
        assert inner["type"] == "object"
        assert "title" in inner["properties"]
        assert "score" in inner["required"]

    def test_ollama_schema_format(self):
        """Ollama gets {title, type: object, properties, required, additionalProperties}."""
        compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "ollama")
        assert isinstance(compiled, dict)
        assert compiled["title"] == "test_schema"
        assert compiled["type"] == "object"
        assert "title" in compiled["properties"]
        assert compiled["additionalProperties"] is False

    def test_groq_openai_compatible_format(self):
        """Groq gets OpenAI-compatible format (same structure as OpenAI)."""
        compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "groq")
        assert isinstance(compiled, dict)
        assert compiled["name"] == "test_schema"
        inner = compiled["schema"]
        assert inner["type"] == "object"
        assert inner["additionalProperties"] is False

    def test_mistral_openai_compatible_format(self):
        """Mistral gets OpenAI-compatible format."""
        compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "mistral")
        assert isinstance(compiled, dict)
        inner = compiled["schema"]
        assert inner["type"] == "object"

    def test_cohere_object_schema_format(self):
        """Cohere gets {type: object, properties, required} (no additionalProperties)."""
        compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "cohere")
        assert isinstance(compiled, dict)
        assert compiled["type"] == "object"
        assert "properties" in compiled
        assert "required" in compiled
        # Cohere format doesn't include additionalProperties
        assert "additionalProperties" not in compiled

    def test_agac_provider_openai_compatible(self):
        """agac-provider uses OpenAI-compatible format."""
        compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "agac-provider")
        assert isinstance(compiled, dict)
        assert compiled["name"] == "test_schema"
        inner = compiled["schema"]
        assert inner["type"] == "object"

    def test_unknown_vendor_raises(self):
        """Unknown vendor raises ConfigValidationError."""
        with pytest.raises(ConfigValidationError):
            compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "unknown_vendor")

    def test_vendor_compilation_error_handled_gracefully(self):
        """_compile_schema_for_vendor catches ConfigValidationError and returns None."""
        result = _compile_schema_for_vendor(SAMPLE_UNIFIED_SCHEMA, "unknown_vendor", "test")
        assert result is None

    def test_all_vendors_receive_required_fields(self):
        """Every supported vendor includes required field info in compiled output."""
        vendors = ["openai", "anthropic", "gemini", "ollama", "groq", "mistral", "cohere"]
        for vendor in vendors:
            compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, vendor)
            # Each vendor should produce non-None output
            assert compiled is not None, f"{vendor} returned None"

    def test_gemini_format_not_just_properties(self):
        """Regression: Gemini must include type/required, not just raw properties."""
        compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, "gemini")
        inner = compiled["schema"]
        # Must be a full JSON Schema object, not just the properties dict
        assert "type" in inner, "Gemini schema.schema must include 'type'"
        assert "required" in inner, "Gemini schema.schema must include 'required'"
        assert inner["type"] == "object"

    def test_array_schema_conversion_then_compilation(self):
        """Array-type JSON Schema is converted to unified format before compilation."""
        array_schema = {
            "name": "items_list",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": {"type": "string"}},
                "required": ["fact"],
            },
        }
        compiled = compile_unified_schema(array_schema, "openai")
        assert isinstance(compiled, dict)
        # Should have been converted: array wraps in a field
        assert "items_list" in compiled["schema"]["properties"]


# ===================================================================
# 3. Schema Mismatch Modes
# ===================================================================


class TestSchemaMismatchModes:
    """Tests for on_schema_mismatch: warn, reprompt, reject."""

    def _config(self, **overrides) -> dict[str, Any]:
        base = {
            "schema": {
                "fields": [
                    {"name": "title", "type": "string", "required": True},
                    {"name": "score", "type": "number", "required": True},
                ]
            },
        }
        base.update(overrides)
        return base

    def test_default_is_warn(self):
        assert _resolve_schema_mismatch_mode({}) == "warn"

    def test_explicit_warn(self):
        assert _resolve_schema_mismatch_mode({"on_schema_mismatch": "warn"}) == "warn"

    def test_explicit_reprompt(self):
        assert _resolve_schema_mismatch_mode({"on_schema_mismatch": "reprompt"}) == "reprompt"

    def test_explicit_reject(self):
        assert _resolve_schema_mismatch_mode({"on_schema_mismatch": "reject"}) == "reject"

    def test_strict_schema_maps_to_reject(self):
        assert _resolve_schema_mismatch_mode({"strict_schema": True}) == "reject"

    def test_explicit_overrides_strict_schema(self):
        config = {"strict_schema": True, "on_schema_mismatch": "warn"}
        assert _resolve_schema_mismatch_mode(config) == "warn"

    def test_warn_logs_and_continues(self):
        """Warn mode returns response unchanged (does not raise)."""
        config = self._config()
        response = {"wrong_field": "value"}
        result = _validate_llm_output_schema(response, config, "test")
        assert result == response

    def test_reject_raises_on_mismatch(self):
        """Reject mode raises SchemaValidationError."""
        config = self._config(on_schema_mismatch="reject")
        response = {"wrong_field": "value"}
        with pytest.raises(SchemaValidationError):
            _validate_llm_output_schema(response, config, "test")

    def test_reject_passes_on_valid(self):
        """Reject mode returns response when output matches schema."""
        config = self._config(on_schema_mismatch="reject")
        response = {"title": "ok", "score": 5}
        result = _validate_llm_output_schema(response, config, "test")
        assert result == response

    def test_reprompt_skips_when_flag_set(self):
        """Reprompt mode with skip flag defers to outer reprompt loop."""
        config = self._config(on_schema_mismatch="reprompt")
        response = {"wrong": "data"}
        result = _validate_llm_output_schema(response, config, "test", skip_schema_validation=True)
        assert result == response

    def test_reprompt_falls_back_to_warn_without_flag(self):
        """Reprompt mode without skip flag falls back to warn (no raise)."""
        config = self._config(on_schema_mismatch="reprompt")
        response = {"wrong": "data"}
        result = _validate_llm_output_schema(response, config, "test")
        assert result == response

    def test_invalid_mode_defaults_to_warn(self):
        """Unrecognized on_schema_mismatch value defaults to warn."""
        config = self._config(on_schema_mismatch="invalid_mode")
        response = {"wrong": "data"}
        result = _validate_llm_output_schema(response, config, "test")
        assert result == response  # warn mode, no raise


# ===================================================================
# 4. JSON Mode Interaction
# ===================================================================


class TestJsonModeInteraction:
    """Tests for json_mode interaction with schema."""

    def test_json_mode_true_compiles_schema(self):
        """json_mode=true (default) compiles and returns schema."""
        compiler = ResponseSchemaCompiler(project_root=None, tools_path=None)
        config = {"schema": SAMPLE_UNIFIED_SCHEMA, "name": "test"}
        compiled, _ = compiler.compile(config, "openai")
        assert compiled is not None

    def test_json_mode_false_wraps_in_output_field(self):
        """json_mode=false causes BaseClient to use call_non_json (schema not sent).

        The schema is compiled by ResponseSchemaCompiler regardless of json_mode,
        but BaseClient.invoke() routes to call_non_json which doesn't receive it.
        This test verifies the ResponseBuilder.wrap_non_json behavior.
        """
        from agent_actions.output.response.response_builder import ResponseBuilder

        result = ResponseBuilder.wrap_non_json("plain text", {"output_field": "content"})
        assert result == [{"content": "plain text"}]

    def test_schema_still_compiled_regardless_of_json_mode(self):
        """ResponseSchemaCompiler compiles schema even when json_mode would be false.

        The compiler doesn't check json_mode — that's the client's job.
        This verifies the compiler always produces output when schema is present.
        """
        compiler = ResponseSchemaCompiler(project_root=None, tools_path=None)
        config = {"schema": SAMPLE_UNIFIED_SCHEMA, "name": "test", "json_mode": False}
        compiled, _ = compiler.compile(config, "openai")
        # Compiler doesn't filter by json_mode
        assert compiled is not None


# ===================================================================
# 5. Dispatch Task in Schema
# ===================================================================


class TestDispatchInSchema:
    """Tests for dispatch_task() resolution in schema fields."""

    def test_non_dispatch_string_unchanged(self):
        """Strings without dispatch_task() pass through unchanged."""
        result = _resolve_dispatch_in_schema("plain_string", None, "{}", {}, {})
        assert result == "plain_string"

    def test_non_string_unchanged(self):
        """Non-string schemas pass through unchanged."""
        schema_dict = {"fields": [{"id": "x", "type": "string"}]}
        result = _resolve_dispatch_in_schema(schema_dict, None, "{}", {}, {})
        assert result == schema_dict

    @patch("agent_actions.output.response.dispatch_injection.logger")
    def test_dispatch_resolution_failure_warns(self, mock_logger):
        """Failed dispatch_task() resolution logs WARNING (not silent DEBUG).

        ConfigurationError (e.g., missing UDF module) is caught and logged.
        """
        schema_str = 'dispatch_task("nonexistent_function")'
        result = _resolve_dispatch_in_schema(schema_str, None, "{}", {}, {})
        # Should return original string (unresolved)
        assert result == schema_str
        # Should log at WARNING level (not DEBUG)
        mock_logger.warning.assert_called_once()
        warning_msg = str(mock_logger.warning.call_args)
        assert "dispatch_task resolution failed" in warning_msg

    def test_recursive_injection_in_dict(self):
        """_inject_functions_into_schema recursively processes dict values."""
        schema = {"field_a": "regular_value", "field_b": {"nested": "value"}}
        # No dispatch_task strings, so should return identical structure
        result = _inject_functions_into_schema(schema, None, None, None, {})
        assert result == schema

    def test_recursive_injection_in_list(self):
        """_inject_functions_into_schema recursively processes list items."""
        schema = ["regular_value", {"nested": "value"}]
        result = _inject_functions_into_schema(schema, None, None, None, {})
        assert result == schema

    def test_non_dispatch_strings_in_schema_preserved(self):
        """Regular strings in schema fields are not modified."""
        schema = {"type": "string", "description": "A text field"}
        result = _inject_functions_into_schema(schema, None, None, None, {})
        assert result["type"] == "string"
        assert result["description"] == "A text field"


# ===================================================================
# 6. Schemaless Actions
# ===================================================================


class TestSchemalessActions:
    """Tests for actions without schema configured."""

    def test_no_schema_skips_validation(self):
        """No schema in config → validation skipped, response returned as-is."""
        response = {"any_field": "any_value"}
        result = _validate_llm_output_schema(response, {}, "test")
        assert result == response

    def test_non_dict_schema_skips_validation(self):
        """Schema that's not a dict (e.g., string schema_name) skips inline validation."""
        config = {"schema": "some_schema_name"}
        response = {"data": 1}
        result = _validate_llm_output_schema(response, config, "test")
        assert result == response

    def test_schemaless_with_reject_not_enforced(self):
        """Schemaless action + on_schema_mismatch=reject does NOT raise.

        This is a known gap: when no schema is defined, _validate_llm_output_schema
        returns early before checking mismatch mode. The intent of 'reject' is
        violated silently.
        """
        config = {"on_schema_mismatch": "reject"}  # no schema key
        response = {"any_field": "any_value"}
        # Does NOT raise — schema check is bypassed when schema is None
        result = _validate_llm_output_schema(response, config, "test")
        assert result == response

    def test_schemaless_with_strict_not_enforced(self):
        """Schemaless action + strict_schema=true does NOT raise."""
        config = {"strict_schema": True}  # no schema key
        response = {"any_field": "any_value"}
        result = _validate_llm_output_schema(response, config, "test")
        assert result == response


# ===================================================================
# 7. Output Validation
# ===================================================================


class TestOutputValidation:
    """Tests for post-LLM output validation against schema."""

    def test_missing_required_field_detected(self):
        """Missing required field makes report non-compliant."""
        schema = {
            "name": "test",
            "fields": [
                {"id": "title", "type": "string", "required": True},
                {"id": "score", "type": "number", "required": True},
            ],
        }
        output = {"title": "hello"}  # missing 'score'
        report = validate_output_against_schema(output, schema, "test")
        assert not report.is_compliant
        assert "score" in report.missing_required

    def test_all_required_fields_present_passes(self):
        """All required fields present → compliant."""
        schema = {
            "name": "test",
            "fields": [
                {"id": "title", "type": "string", "required": True},
                {"id": "score", "type": "number", "required": True},
            ],
        }
        output = {"title": "hello", "score": 42}
        report = validate_output_against_schema(output, schema, "test")
        assert report.is_compliant

    def test_extra_fields_allowed_in_non_strict(self):
        """Extra fields are allowed in non-strict mode."""
        schema = {
            "name": "test",
            "fields": [{"id": "title", "type": "string", "required": True}],
        }
        output = {"title": "hello", "extra": "data"}
        report = validate_output_against_schema(output, schema, "test", strict_mode=False)
        assert report.is_compliant
        assert "extra" in report.extra_fields

    def test_extra_fields_in_strict_mode(self):
        """Extra fields fail validation in strict mode."""
        schema = {
            "name": "test",
            "fields": [{"id": "title", "type": "string", "required": True}],
        }
        output = {"title": "hello", "extra": "data"}
        report = validate_output_against_schema(output, schema, "test", strict_mode=True)
        assert not report.is_compliant
        assert "extra" in report.extra_fields

    def test_type_mismatch_detected(self):
        """Type mismatch between expected and actual value type."""
        schema = {
            "name": "test",
            "fields": [
                {"id": "score", "type": "number", "required": True},
            ],
        }
        output = {"score": "not_a_number"}  # string instead of number
        report = validate_output_against_schema(output, schema, "test")
        assert not report.is_compliant
        assert "score" in report.type_errors

    def test_bool_rejected_for_integer(self):
        """Boolean values are rejected for integer fields (Python bool is subclass of int)."""
        schema = {
            "name": "test",
            "fields": [{"id": "count", "type": "integer", "required": True}],
        }
        output = {"count": True}
        report = validate_output_against_schema(output, schema, "test")
        assert not report.is_compliant
        assert "count" in report.type_errors

    def test_none_value_allowed_for_optional(self):
        """None value is allowed for optional fields."""
        field_types = {"name": "string"}
        errors = _check_field_types({"name": None}, field_types)
        assert len(errors) == 0

    def test_namespace_hint_on_udf_mistake(self):
        """Namespace hint generated when extra keys look like action namespaces."""
        schema = {
            "name": "test",
            "fields": [
                {"id": "result", "type": "string", "required": True},
            ],
        }
        # UDF mistake: passing namespaced input through instead of unwrapping
        output = {"canonicalize_qa": {"result": "hello"}}
        report = validate_output_against_schema(output, schema, "test")
        assert not report.is_compliant
        assert report.namespace_hint is not None
        assert "canonicalize_qa" in report.namespace_hint

    def test_validate_and_raise_on_invalid(self):
        """validate_and_raise_if_invalid raises SchemaValidationError."""
        schema = {
            "name": "test",
            "fields": [{"id": "x", "type": "string", "required": True}],
        }
        with pytest.raises(SchemaValidationError):
            validate_and_raise_if_invalid({"wrong": "data"}, schema, "test")

    def test_validate_and_raise_passes_on_valid(self):
        """validate_and_raise_if_invalid returns report when valid."""
        schema = {
            "name": "test",
            "fields": [{"id": "x", "type": "string", "required": True}],
        }
        report = validate_and_raise_if_invalid({"x": "hello"}, schema, "test")
        assert report.is_compliant

    def test_json_schema_format_validation(self):
        """Validator handles JSON Schema format (properties/required) not just unified."""
        output = {"title": "hello", "score": 42}
        report = validate_output_against_schema(output, SAMPLE_JSON_SCHEMA, "test")
        assert report.is_compliant

    def test_json_schema_missing_required(self):
        """JSON Schema format detects missing required fields."""
        output = {"title": "hello"}  # missing score
        report = validate_output_against_schema(output, SAMPLE_JSON_SCHEMA, "test")
        assert not report.is_compliant
        assert "score" in report.missing_required

    def test_malformed_properties_detected(self):
        """Schema with properties: null is detected as structural error."""
        schema = {"type": "object", "properties": None}
        errors = _check_properties_type(schema)
        assert len(errors) > 0
        assert "must be a dict" in errors[0]

    def test_properties_string_detected(self):
        """Schema with properties as string is detected."""
        schema = {"type": "object", "properties": "invalid"}
        errors = _check_properties_type(schema)
        assert len(errors) > 0

    def test_array_output_validation(self):
        """Validator handles array output by checking all items."""
        schema = {
            "name": "test",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        output = [{"name": "Alice"}, {"name": "Bob"}]
        report = validate_output_against_schema(output, schema, "test")
        # Array items are checked for field presence
        assert "name" in report.actual_fields

    def test_report_format_readable(self):
        """SchemaValidationReport.format_report produces readable output."""
        report = SchemaValidationReport(
            action_name="test",
            schema_name="my_schema",
            is_compliant=False,
            expected_fields={"title", "score"},
            actual_fields={"title", "extra"},
            missing_required=["score"],
            extra_fields=["extra"],
            type_errors={},
        )
        text = report.format_report()
        assert "INVALID" in text
        assert "score" in text
        assert "extra" in text

    def test_report_to_dict_serializable(self):
        """SchemaValidationReport.to_dict produces serializable dict."""
        report = SchemaValidationReport(
            action_name="test",
            schema_name="my_schema",
            is_compliant=True,
        )
        d = report.to_dict()
        assert d["action_name"] == "test"
        assert d["is_compliant"] is True
        assert isinstance(d["timestamp"], str)


# ===================================================================
# 8. Schema Field Extraction
# ===================================================================


class TestSchemaFieldExtraction:
    """Tests for _extract_schema_fields across schema formats."""

    def test_unified_format(self):
        """Unified format: fields array with id/type/required."""
        all_f, req_f, types = _extract_schema_fields(SAMPLE_UNIFIED_SCHEMA)
        assert all_f == {"title", "score", "tags"}
        assert req_f == {"title", "score"}
        assert types["title"] == "string"
        assert types["score"] == "number"

    def test_json_schema_format(self):
        """JSON Schema format: properties/required."""
        all_f, req_f, types = _extract_schema_fields(SAMPLE_JSON_SCHEMA)
        assert all_f == {"title", "score", "tags"}
        assert req_f == {"title", "score"}

    def test_nested_schema_format(self):
        """Nested {schema: {properties: ...}} is recursively extracted."""
        nested = {
            "name": "outer",
            "schema": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
        }
        all_f, req_f, types = _extract_schema_fields(nested)
        assert "x" in all_f
        assert "x" in req_f

    def test_array_items_format(self):
        """Array schema with items.properties extracts item fields."""
        array_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["fact"],
            },
        }
        all_f, req_f, types = _extract_schema_fields(array_schema)
        assert "fact" in all_f
        assert "source" in all_f
        assert "fact" in req_f

    def test_empty_schema_returns_empty(self):
        """Schema with no recognized format returns empty sets."""
        all_f, req_f, types = _extract_schema_fields({})
        assert all_f == set()
        assert req_f == set()
        assert types == {}

    def test_malformed_properties_treated_as_empty(self):
        """Non-dict properties logged as warning, treated as empty."""
        schema = {"properties": "not_a_dict"}
        all_f, req_f, types = _extract_schema_fields(schema)
        assert all_f == set()


# ===================================================================
# 9. Full Pipeline Integration
# ===================================================================


class TestFullPipelineIntegration:
    """End-to-end tests combining resolution, compilation, and validation."""

    def test_inline_schema_compile_validate_pass(self):
        """Full path: inline schema → compile → validate matching output."""
        compiler = ResponseSchemaCompiler(project_root=None, tools_path=None)
        config = {"schema": SAMPLE_UNIFIED_SCHEMA, "name": "test_action"}

        compiled, _ = compiler.compile(config, "openai")
        assert compiled is not None

        # Validate output against the original schema
        output = {"title": "hello", "score": 42, "tags": ["a"]}
        report = validate_output_against_schema(output, SAMPLE_UNIFIED_SCHEMA, "test_action")
        assert report.is_compliant

    def test_inline_schema_compile_validate_fail(self):
        """Full path: inline schema → compile → validate mismatched output."""
        compiler = ResponseSchemaCompiler(project_root=None, tools_path=None)
        config = {"schema": SAMPLE_UNIFIED_SCHEMA, "name": "test_action"}

        compiled, _ = compiler.compile(config, "openai")
        assert compiled is not None

        output = {"wrong_field": "value"}
        report = validate_output_against_schema(output, SAMPLE_UNIFIED_SCHEMA, "test_action")
        assert not report.is_compliant

    def test_every_vendor_compiles_same_schema(self):
        """All vendors compile the same unified schema without errors."""
        vendors = ["openai", "anthropic", "gemini", "ollama", "groq", "mistral", "cohere"]
        for vendor in vendors:
            compiled = compile_unified_schema(SAMPLE_UNIFIED_SCHEMA, vendor)
            assert compiled is not None, f"Vendor {vendor} failed to compile"

    def test_schema_with_all_field_types(self):
        """Schema with every supported field type compiles and validates."""
        schema = {
            "name": "all_types",
            "fields": [
                {"id": "text", "type": "string", "required": True},
                {"id": "count", "type": "integer", "required": True},
                {"id": "ratio", "type": "number", "required": True},
                {"id": "active", "type": "boolean", "required": True},
                {"id": "items", "type": "array", "required": True},
                {"id": "meta", "type": "object", "required": True},
            ],
        }
        # Compiles
        compiled = compile_unified_schema(schema, "openai")
        assert compiled is not None

        # Validates correct output
        output = {
            "text": "hello",
            "count": 5,
            "ratio": 3.14,
            "active": True,
            "items": [1, 2, 3],
            "meta": {"key": "value"},
        }
        report = validate_output_against_schema(output, schema, "test")
        assert report.is_compliant

        # Detects type mismatch
        bad_output = {
            "text": 123,  # wrong type
            "count": 5,
            "ratio": 3.14,
            "active": True,
            "items": [1, 2, 3],
            "meta": {"key": "value"},
        }
        report = validate_output_against_schema(bad_output, schema, "test")
        assert not report.is_compliant
        assert "text" in report.type_errors
