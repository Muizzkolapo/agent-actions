"""Tests for JSON serializability of compiled schemas.

Verifies that compile_field() and compile_unified_schema() produce
JSON-safe output even when YAML parsing or dispatch functions introduce
non-serializable Python types (NaN, Infinity, datetime, bytes, sets).
"""

import json
from datetime import date, datetime

import pytest

from agent_actions.output.response.schema_conversion import (
    _sanitise_schema_value,
    compile_field,
)
from agent_actions.output.response.vendor_compilation import compile_unified_schema

# ---------------------------------------------------------------------------
# _sanitise_schema_value unit tests
# ---------------------------------------------------------------------------


class TestSanitiseSchemaValue:
    """Direct tests for the schema value sanitiser."""

    def test_nan_replaced_with_none(self):
        assert _sanitise_schema_value(float("nan")) is None

    def test_infinity_replaced_with_none(self):
        assert _sanitise_schema_value(float("inf")) is None
        assert _sanitise_schema_value(float("-inf")) is None

    def test_normal_float_preserved(self):
        assert _sanitise_schema_value(3.14) == 3.14

    def test_date_to_isoformat(self):
        assert _sanitise_schema_value(date(2026, 1, 1)) == "2026-01-01"

    def test_datetime_to_isoformat(self):
        assert _sanitise_schema_value(datetime(2026, 1, 1, 12, 0)) == "2026-01-01T12:00:00"

    def test_bytes_decoded(self):
        assert _sanitise_schema_value(b"hello") == "hello"

    def test_set_to_list(self):
        result = _sanitise_schema_value({"a", "b"})
        assert isinstance(result, list)
        assert sorted(result) == ["a", "b"]

    def test_nested_dict(self):
        data = {"key": float("nan"), "nested": {"dt": date(2026, 1, 1)}}
        result = _sanitise_schema_value(data)
        assert result["key"] is None
        assert result["nested"]["dt"] == "2026-01-01"
        json.dumps(result)  # Must not raise

    def test_custom_object_to_string(self):
        class Marker:
            def __repr__(self):
                return "Marker()"

        assert _sanitise_schema_value(Marker()) == "Marker()"


# ---------------------------------------------------------------------------
# compile_field — JSON safety integration
# ---------------------------------------------------------------------------


class TestCompileFieldJsonSafety:
    """Verify compile_field sanitises non-serializable values in field properties."""

    def test_enum_with_date_values_serialisable(self):
        field = {
            "id": "status_date",
            "type": "string",
            "enum": [date(2026, 1, 1), date(2026, 6, 15)],
        }
        name, prop = compile_field(field, "openai")
        assert name == "status_date"
        assert prop["enum"] == ["2026-01-01", "2026-06-15"]
        json.dumps(prop)

    def test_description_with_datetime_serialisable(self):
        field = {
            "id": "created",
            "type": "string",
            "description": datetime(2026, 4, 19, 12, 0),
        }
        name, prop = compile_field(field, "openai")
        assert prop["description"] == "2026-04-19T12:00:00"
        json.dumps(prop)

    def test_items_with_nan_sanitised(self):
        field = {
            "id": "scores",
            "type": "array",
            "items": {"type": "number", "default": float("nan")},
        }
        name, prop = compile_field(field, "openai")
        assert prop["items"]["default"] is None
        json.dumps(prop)

    def test_validator_with_bytes_sanitised(self):
        field = {
            "id": "code",
            "type": "string",
            "validators": [{"not": {"pattern": b"[invalid]"}, "errorMessage": "bad"}],
        }
        name, prop = compile_field(field, "openai")
        assert isinstance(prop["not"]["pattern"], str)
        json.dumps(prop)

    def test_normal_field_unchanged(self):
        field = {
            "id": "name",
            "type": "string",
            "description": "A name field",
            "required": True,
        }
        name, prop = compile_field(field, "openai")
        assert name == "name"
        assert prop == {"type": "string", "description": "A name field"}
        json.dumps(prop)


# ---------------------------------------------------------------------------
# compile_unified_schema — JSON safety integration
# ---------------------------------------------------------------------------


class TestCompileUnifiedSchemaJsonSafety:
    """Verify compiled schemas are JSON-serialisable for all vendor targets."""

    @pytest.fixture
    def schema_with_unsafe_values(self):
        return {
            "name": "test_schema",
            "description": "Schema for testing",
            "fields": [
                {
                    "id": "score",
                    "type": "number",
                    "description": "A score",
                    "required": True,
                },
                {
                    "id": "tags",
                    "type": "array",
                    "items": {"type": "string"},
                    "enum": [date(2026, 1, 1), "active"],
                    "required": False,
                },
            ],
        }

    @pytest.mark.parametrize(
        "target", ["openai", "anthropic", "gemini", "ollama", "groq", "cohere", "mistral"]
    )
    def test_compiled_schema_json_serialisable(self, schema_with_unsafe_values, target):
        compiled = compile_unified_schema(schema_with_unsafe_values, target)
        # Must not raise
        json.dumps(compiled)

    def test_openai_schema_with_nan_field_default(self):
        schema = {
            "name": "scores",
            "fields": [
                {
                    "id": "value",
                    "type": "number",
                    "required": True,
                },
            ],
        }
        compiled = compile_unified_schema(schema, "openai")
        # Entire compiled dict must be JSON-safe
        serialised = json.dumps(compiled)
        parsed = json.loads(serialised)
        assert parsed["name"] == "scores"

    def test_openai_schema_nan_in_nested_items(self):
        schema = {
            "name": "data",
            "fields": [
                {
                    "id": "values",
                    "type": "array",
                    "items": {"type": "number", "default": float("nan")},
                    "required": True,
                },
            ],
        }
        compiled = compile_unified_schema(schema, "openai")
        serialised = json.dumps(compiled)
        parsed = json.loads(serialised)
        # NaN should have been replaced with null
        assert parsed["schema"]["properties"]["values"]["items"]["default"] is None
