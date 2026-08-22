"""Unit tests for schema_output_validator module."""

import pytest

from agent_actions.errors import SchemaValidationError
from agent_actions.validation.schema_output_validator import (
    SchemaValidationReport,
    validate_and_raise_if_invalid,
    validate_output_against_schema,
)


class TestSchemaValidationReport:
    """Tests for SchemaValidationReport dataclass."""

    def test_format_report(self):
        """Test formatting a validation report."""
        report = SchemaValidationReport(
            action_name="test_action",
            schema_name="test_schema",
            is_compliant=False,
            missing_required=["required_field"],
            extra_fields=["unknown_field"],
            type_errors={"age": ("integer", "string")},
            validation_errors=["Missing required field"],
        )
        formatted = report.format_report()
        assert "test_action" in formatted
        assert "test_schema" in formatted
        assert "INVALID" in formatted
        assert "required_field" in formatted
        assert "unknown_field" in formatted


class TestValidateOutputAgainstSchema:
    """Tests for validate_output_against_schema function."""

    def test_valid_output_unified_format(self):
        """Test validation with valid output against unified schema format."""
        schema = {
            "name": "test_schema",
            "fields": [
                {"id": "name", "type": "string", "required": True},
                {"id": "age", "type": "number", "required": False},
            ],
        }
        output = {"name": "John", "age": 30}

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant
        assert report.expected_fields == {"name", "age"}
        assert report.actual_fields == {"name", "age"}
        assert len(report.missing_required) == 0

    def test_missing_required_field(self):
        """Test validation fails when required field is missing."""
        schema = {
            "name": "test_schema",
            "fields": [
                {"id": "name", "type": "string", "required": True},
                {"id": "age", "type": "number", "required": True},
            ],
        }
        output = {"name": "John"}  # Missing 'age'

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "age" in report.missing_required

    def test_missing_optional_field(self):
        """Test validation passes when optional field is missing."""
        schema = {
            "name": "test_schema",
            "fields": [
                {"id": "name", "type": "string", "required": True},
                {"id": "age", "type": "number", "required": False},
            ],
        }
        output = {"name": "John"}  # Missing optional 'age'

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant
        assert "age" in report.missing_optional

    def test_extra_fields_non_strict(self):
        """Test extra fields don't fail validation in non-strict mode."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John", "extra": "value"}

        report = validate_output_against_schema(output, schema, "test_action", strict_mode=False)

        assert report.is_compliant
        assert "extra" in report.extra_fields

    def test_extra_fields_strict(self):
        """Test extra fields fail validation in strict mode."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John", "extra": "value"}

        report = validate_output_against_schema(output, schema, "test_action", strict_mode=True)

        assert not report.is_compliant
        assert "extra" in report.extra_fields

    def test_type_mismatch(self):
        """Test type mismatch is detected."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "age", "type": "integer", "required": True}],
        }
        output = {"age": "not a number"}

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "age" in report.type_errors
        assert report.type_errors["age"] == ("integer", "str")

    def test_bool_rejected_for_integer_type(self):
        """Test that bool values are rejected for integer type (bool subclasses int in Python)."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "count", "type": "integer", "required": True}],
        }
        output = {"count": True}

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "count" in report.type_errors
        assert report.type_errors["count"] == ("integer", "bool")

    def test_bool_rejected_for_number_type(self):
        """Test that bool values are rejected for number type (bool subclasses int/float in Python)."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "score", "type": "number", "required": True}],
        }
        output = {"score": False}

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "score" in report.type_errors
        assert report.type_errors["score"] == ("number", "bool")

    def test_json_schema_format(self):
        """Test validation with JSON Schema format."""
        schema = {
            "name": "test_schema",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }
        output = {"name": "John", "age": 30}

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant
        assert "name" in report.expected_fields
        assert "age" in report.expected_fields

    def test_array_schema_format(self):
        """Test validation with array schema format."""
        schema = {
            "name": "items",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "value": {"type": "number"},
                },
                "required": ["id"],
            },
        }
        output = [{"id": "1", "value": 10}]

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant

    def test_fields_format_top_level_required_array(self):
        """Top-level required array is honored for fields-format schemas."""
        schema = {
            "name": "test_schema",
            "required": ["name", "age"],
            "fields": [
                {"id": "name", "type": "string"},
                {"id": "age", "type": "number"},
                {"id": "nickname", "type": "string"},
            ],
        }
        output = {"name": "John", "nickname": "JD"}  # Missing required 'age'

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "age" in report.missing_required
        assert "nickname" not in report.missing_required

    def test_fields_format_per_field_overrides_top_level(self):
        """Per-field required: false overrides top-level required array."""
        schema = {
            "name": "test_schema",
            "required": ["name", "age"],
            "fields": [
                {"id": "name", "type": "string"},
                {"id": "age", "type": "number", "required": False},
            ],
        }
        output = {"name": "John"}  # Missing 'age' but per-field says optional

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant
        assert "age" in report.missing_optional

    def test_fields_format_per_field_required_true_without_top_level(self):
        """Per-field required: true works without top-level array (existing behavior)."""
        schema = {
            "name": "test_schema",
            "fields": [
                {"id": "name", "type": "string", "required": True},
                {"id": "age", "type": "number"},
            ],
        }
        output = {"age": 30}  # Missing required 'name'

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert "name" in report.missing_required

    def test_fields_format_no_required_anywhere(self):
        """Empty output fails when schema declares fields, even if none are required.

        An empty object is semantically useless when fields are declared — the
        LLM produced nothing.  This guards against {} slipping through when
        ``required`` is empty (see spec #43).
        """
        schema = {
            "name": "test_schema",
            "fields": [
                {"id": "name", "type": "string"},
                {"id": "age", "type": "number"},
            ],
        }
        output = {}  # All missing — now rejected even without required

        report = validate_output_against_schema(output, schema, "test_action")

        assert not report.is_compliant
        assert any("Empty object" in e for e in report.validation_errors)

    def test_fields_format_top_level_unknown_field_ignored(self):
        """Top-level required referencing a non-existent field ID is ignored."""
        schema = {
            "name": "test_schema",
            "required": ["nonexistent"],
            "fields": [
                {"id": "name", "type": "string"},
            ],
        }
        output = {"name": "John"}

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant

    def test_nested_openai_schema_format(self):
        """Test validation with nested OpenAI-style schema format."""
        schema = {
            "name": "test_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "result": {"type": "string"},
                },
                "required": ["result"],
            },
        }
        output = {"result": "success"}

        report = validate_output_against_schema(output, schema, "test_action")

        assert report.is_compliant


class TestValidateAndRaiseIfInvalid:
    """Tests for validate_and_raise_if_invalid function."""

    def test_valid_output_returns_report(self):
        """Test valid output returns report without raising."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John"}

        report = validate_and_raise_if_invalid(output, schema, "test_action")

        assert report.is_compliant

    def test_invalid_output_raises_error(self):
        """Test invalid output raises SchemaValidationError."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {}  # Missing required 'name'

        with pytest.raises(SchemaValidationError) as exc_info:
            validate_and_raise_if_invalid(output, schema, "test_action")

        error = exc_info.value
        assert error.schema_name == "test_schema"
        assert error.action_name == "test_action"
        assert "name" in error.missing_fields

    def test_strict_mode_fails_on_extra_fields(self):
        """Test strict mode raises error on extra fields."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John", "extra": "value"}

        with pytest.raises(SchemaValidationError) as exc_info:
            validate_and_raise_if_invalid(output, schema, "test_action", strict_mode=True)

        error = exc_info.value
        assert "extra" in error.extra_fields


# ---------------------------------------------------------------------------
# Schema-echo / empty-object detection (spec #43)
# ---------------------------------------------------------------------------

# Fixture: exact schema-echo payload from bug evidence
SCHEMA_ECHO_PAYLOAD = {
    "title": "InlineSchema",
    "type": "object",
    "properties": {"optimal_code": {"type": "string"}},
    "required": [],
    "additionalProperties": False,
}


class TestSchemaEchoRejection:
    """LLM returns the JSON Schema definition itself instead of conforming data."""

    def test_schema_echo_is_non_compliant(self):
        schema = {
            "name": "code_schema",
            "properties": {"optimal_code": {"type": "string"}},
            "required": ["optimal_code"],
        }
        report = validate_output_against_schema(
            SCHEMA_ECHO_PAYLOAD, schema, "generate_optimal_code"
        )
        assert not report.is_compliant
        assert any("Schema-echo" in e for e in report.validation_errors)
        assert "optimal_code" not in report.actual_fields

    def test_schema_echo_with_optional_fields(self):
        """Schema-echo fails even when no fields are required."""
        schema = {
            "name": "code_schema",
            "properties": {"optimal_code": {"type": "string"}},
        }
        report = validate_output_against_schema(
            SCHEMA_ECHO_PAYLOAD, schema, "generate_optimal_code"
        )
        assert not report.is_compliant
        assert any("Schema-echo" in e for e in report.validation_errors)

    def test_schema_echo_fields_format(self):
        """Schema-echo detected for fields-format schemas too."""
        schema = {
            "name": "code_schema",
            "fields": [{"id": "optimal_code", "type": "string", "required": True}],
        }
        report = validate_output_against_schema(
            SCHEMA_ECHO_PAYLOAD, schema, "generate_optimal_code"
        )
        assert not report.is_compliant
        assert any("Schema-echo" in e for e in report.validation_errors)


class TestEmptyObjectRejection:
    """LLM returns {} when schema declares fields."""

    def test_empty_dict_rejected_with_required_fields(self):
        schema = {
            "name": "quote_schema",
            "properties": {"final_source_quote": {"type": "string"}},
            "required": ["final_source_quote"],
        }
        report = validate_output_against_schema({}, schema, "consolidate_answer")
        assert not report.is_compliant
        assert any("Empty object" in e for e in report.validation_errors)

    def test_empty_dict_rejected_even_without_required(self):
        """Empty {} fails even when schema has no required fields (spec #43)."""
        schema = {
            "name": "quote_schema",
            "properties": {"final_source_quote": {"type": "string"}},
        }
        report = validate_output_against_schema({}, schema, "consolidate_answer")
        assert not report.is_compliant
        assert any("Empty object" in e for e in report.validation_errors)

    def test_empty_dict_ok_when_schema_has_no_fields(self):
        """Schema with no declared fields: {} is valid (nothing expected)."""
        schema = {"name": "empty_schema", "properties": {}}
        report = validate_output_against_schema({}, schema, "noop_action")
        assert report.is_compliant


class TestMetaKeyFalsePositive:
    """Schema that legitimately declares a field named 'type' or other meta-key."""

    def test_legitimate_type_field_allowed(self):
        """If schema declares 'type' as an output field, output with 'type' is valid."""
        schema = {
            "name": "classify_schema",
            "properties": {
                "type": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["type"],
        }
        output = {"type": "question", "confidence": 0.95}
        report = validate_output_against_schema(output, schema, "classify")
        assert report.is_compliant
        assert not any("Schema-echo" in e for e in report.validation_errors)

    def test_partial_declared_fields_present(self):
        """Output has some declared fields — not a schema-echo even with extra meta-keys."""
        schema = {
            "name": "test_schema",
            "properties": {
                "answer": {"type": "string"},
                "score": {"type": "number"},
            },
        }
        output = {"answer": "yes", "type": "object"}  # 'type' is extra but 'answer' matches
        report = validate_output_against_schema(output, schema, "test_action")
        assert report.is_compliant
        assert not any("Schema-echo" in e for e in report.validation_errors)
        assert not any("No declared fields" in e for e in report.validation_errors)


class TestInlineSchemaFormat:
    """Inline schema shorthand: keys are field names, values are type strings."""

    def test_inline_schema_extracts_fields(self):
        schema = {"optimal_code": "string", "score": "number"}
        output = {"optimal_code": "const x = 1;", "score": 95}
        report = validate_output_against_schema(output, schema, "generate_code")
        assert report.is_compliant
        assert report.expected_fields == {"optimal_code", "score"}

    def test_inline_schema_rejects_empty_output(self):
        schema = {"optimal_code": "string"}
        report = validate_output_against_schema({}, schema, "generate_code")
        assert not report.is_compliant
        assert any("Empty object" in e for e in report.validation_errors)

    def test_inline_schema_excludes_name_and_description(self):
        """'name' and 'description' are meta-keys, not output fields."""
        schema = {"name": "my_schema", "description": "does stuff", "result": "string"}
        output = {"result": "hello"}
        report = validate_output_against_schema(output, schema, "test_action")
        assert report.is_compliant
        assert report.expected_fields == {"result"}


class TestNamespacedKeyHint:
    """Regression: detect action-namespaced output from tool UDFs."""

    def test_namespaced_output_produces_hint(self):
        """When output has dict-valued extra keys and missing required fields, hint at namespacing."""
        schema = {
            "name": "flatten_schema",
            "fields": [
                {"id": "question_text", "type": "string", "required": True},
                {"id": "answer_text", "type": "string", "required": True},
            ],
        }
        # UDF passed through namespaced input instead of unwrapping
        output = {"canonicalize_qa": {"question_text": "What?", "answer_text": "Yes"}}

        report = validate_output_against_schema(output, schema, "flatten_questions")
        assert not report.is_compliant
        assert "question_text" in report.missing_required
        assert "canonicalize_qa" in report.extra_fields
        assert any("action namespaces" in e for e in report.validation_errors)

    def test_no_hint_when_extra_fields_are_not_dicts(self):
        """Extra scalar fields should NOT trigger the namespace hint."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"wrong_field": "value"}

        report = validate_output_against_schema(output, schema, "test_action")
        assert not report.is_compliant
        assert not any("action namespaces" in e for e in report.validation_errors)

    def test_no_hint_when_no_missing_fields(self):
        """If all required fields are present, no namespace hint even with extra dict keys."""
        schema = {
            "name": "test_schema",
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        output = {"name": "John", "extra_action": {"nested": "data"}}

        report = validate_output_against_schema(output, schema, "test_action")
        assert report.is_compliant
        assert not any("action namespaces" in e for e in report.validation_errors)


class TestAdditionalPropertiesUnderStrictMode:
    """`additionalProperties: true` must relax extra-field rejection.

    `strict_mode` is set by `on_schema_mismatch: reject`
    (processing/helpers.py:216) and receives the raw user schema, so a schema
    that explicitly permits extra keys was still failed on that path. The
    framework advises exactly this setting — `udf_passthrough_validator.py:181`
    tells authors to "set additionalProperties: true" so extra upstream keys are
    not "rejected at runtime" — and then rejected them anyway.
    """

    def test_additional_properties_true_allows_extra_fields(self):
        schema = {
            "name": "s",
            "additionalProperties": True,
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        report = validate_output_against_schema(
            {"name": "John", "extra": "value"}, schema, "a", strict_mode=True
        )
        assert report.is_compliant
        assert not [e for e in report.validation_errors if "Extra fields" in e]

    def test_additional_properties_true_in_nested_schema_allows_extra_fields(self):
        """Compiled/nested `schema` shapes carry the flag one level down."""
        schema = {
            "name": "s",
            "schema": {
                "additionalProperties": True,
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        report = validate_output_against_schema(
            {"name": "John", "extra": "value"}, schema, "a", strict_mode=True
        )
        assert report.is_compliant

    def test_additional_properties_false_still_rejects(self):
        """Invariant: an explicit deny keeps rejecting."""
        schema = {
            "name": "s",
            "additionalProperties": False,
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        report = validate_output_against_schema(
            {"name": "John", "extra": "value"}, schema, "a", strict_mode=True
        )
        assert not report.is_compliant
        assert "extra" in report.extra_fields

    def test_absent_additional_properties_still_rejects_in_strict_mode(self):
        """Invariant: the default must not move — silence still means strict."""
        schema = {"name": "s", "fields": [{"id": "name", "type": "string", "required": True}]}
        report = validate_output_against_schema(
            {"name": "John", "extra": "value"}, schema, "a", strict_mode=True
        )
        assert not report.is_compliant
        assert "extra" in report.extra_fields

    def test_additional_properties_true_does_not_mask_missing_required(self):
        """Permitting extras must not excuse a missing required field."""
        schema = {
            "name": "s",
            "additionalProperties": True,
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        report = validate_output_against_schema(
            {"other": "x", "extra": "value"}, schema, "a", strict_mode=True
        )
        assert not report.is_compliant

    def test_additional_properties_true_in_array_items_allows_extra_fields(self):
        """Array schemas take their declared fields from `items` — read the flag there.

        Found while checking my own fix: a top-level-only lookup disagrees with
        _extract_schema_fields, which descends into items.properties.
        """
        schema = {
            "name": "s",
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": True,
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        report = validate_output_against_schema(
            [{"name": "John", "extra": "value"}], schema, "a", strict_mode=True
        )
        assert report.is_compliant

    def test_array_items_without_flag_still_rejects(self):
        """Invariant: the array shape keeps rejecting when the flag is absent."""
        schema = {
            "name": "s",
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
        report = validate_output_against_schema(
            [{"name": "John", "extra": "value"}], schema, "a", strict_mode=True
        )
        assert not report.is_compliant
        assert "extra" in report.extra_fields

    def test_flag_in_an_unused_nested_wrapper_does_not_permit_extras(self):
        """Reverse direction: the flag must not be read from a level whose fields were ignored.

        Extraction stops at a top-level `fields` block, so a nested `schema`
        wrapper's properties are never used — its flag must not apply either.
        This is what separates mirroring the descent from "search anywhere for
        additionalProperties: true", which would pass every other test here.
        """
        schema = {
            "name": "s",
            "fields": [{"id": "name", "type": "string", "required": True}],
            "schema": {"additionalProperties": True, "properties": {"unused": {}}},
        }
        report = validate_output_against_schema(
            {"name": "John", "extra": "value"}, schema, "a", strict_mode=True
        )
        assert not report.is_compliant
        assert "extra" in report.extra_fields

    def test_properties_format_with_flag_allows_extra_fields(self):
        schema = {
            "name": "s",
            "additionalProperties": True,
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        report = validate_output_against_schema(
            {"name": "John", "extra": "value"}, schema, "a", strict_mode=True
        )
        assert report.is_compliant

    def test_non_boolean_additional_properties_is_not_permission(self):
        """Only the literal `true` permits extras — a schema object does not."""
        schema = {
            "name": "s",
            "additionalProperties": {"type": "string"},
            "fields": [{"id": "name", "type": "string", "required": True}],
        }
        report = validate_output_against_schema(
            {"name": "John", "extra": "value"}, schema, "a", strict_mode=True
        )
        assert not report.is_compliant

    def test_schema_with_no_extractable_fields_never_blanket_accepts(self):
        """A degenerate schema must not let the flag accept arbitrary output.

        `_extract_schema_fields` cannot read an inline shorthand schema that
        carries a non-string meta-key, so it yields zero declared fields and
        every output key counts as extra. Permitting extras there would accept
        anything. The gate therefore requires that fields were actually
        declared — behaviour for this shape is unchanged from before the fix.
        """
        schema = {"a": "string", "additionalProperties": True}

        junk = validate_output_against_schema({"zzz": 1}, schema, "a", strict_mode=True)
        assert not junk.is_compliant

        # Unchanged from main: this shape's fields are not extractable, so the
        # flag cannot take effect. Widening the shape test to fix that is a
        # separate change — it crashes _expand_inline_schema.
        still_strict = validate_output_against_schema(
            {"a": "x", "extra": 1}, schema, "a", strict_mode=True
        )
        assert not still_strict.is_compliant

    def test_inline_shorthand_without_flag_still_rejects_extras(self):
        """Invariant: shorthand schemas keep rejecting extras when no flag is set."""
        report = validate_output_against_schema(
            {"a": "x", "extra": 1}, {"a": "string"}, "a", strict_mode=True
        )
        assert not report.is_compliant
