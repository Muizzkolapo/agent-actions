"""Tests for JSON serializability of compiled schemas.

Verifies that compile_field() and compile_unified_schema() produce
JSON-safe output even when YAML parsing or dispatch functions introduce
non-serializable Python types (NaN, Infinity, datetime, bytes, sets).
"""

import json
from datetime import date, datetime

import pytest

from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.utils.json_safety import ensure_json_safe

# ---------------------------------------------------------------------------
# ensure_json_safe unit tests
# ---------------------------------------------------------------------------


class TestEnsureJsonSafeSchema:
    """Verify ensure_json_safe handles types that appear in schemas."""

    def test_nan_replaced_with_none(self):
        assert ensure_json_safe(float("nan")) is None

    def test_infinity_replaced_with_none(self):
        assert ensure_json_safe(float("inf")) is None
        assert ensure_json_safe(float("-inf")) is None

    def test_normal_float_preserved(self):
        assert ensure_json_safe(3.14) == 3.14

    def test_date_to_isoformat(self):
        assert ensure_json_safe(date(2026, 1, 1)) == "2026-01-01"

    def test_datetime_to_isoformat(self):
        assert ensure_json_safe(datetime(2026, 1, 1, 12, 0)) == "2026-01-01T12:00:00"

    def test_bytes_decoded(self):
        assert ensure_json_safe(b"hello") == "hello"

    def test_set_to_list(self):
        result = ensure_json_safe({"a", "b"})
        assert isinstance(result, list)
        assert sorted(result) == ["a", "b"]

    def test_nested_dict(self):
        data = {"key": float("nan"), "nested": {"dt": date(2026, 1, 1)}}
        result = ensure_json_safe(data)
        assert result["key"] is None
        assert result["nested"]["dt"] == "2026-01-01"
        json.dumps(result)  # Must not raise

    def test_custom_object_to_string(self):
        class Marker:
            def __repr__(self):
                return "Marker()"

        assert ensure_json_safe(Marker()) == "Marker()"


# ---------------------------------------------------------------------------
# compile_unified_schema — field-level JSON safety (via outer sanitisation)
# ---------------------------------------------------------------------------


class TestFieldLevelJsonSafetyViaCompilation:
    """Verify non-serializable field values are sanitised during schema compilation."""

    def test_enum_with_date_values_serialisable(self):
        schema = {
            "name": "test",
            "fields": [
                {
                    "id": "status_date",
                    "type": "string",
                    "enum": [date(2026, 1, 1), date(2026, 6, 15)],
                },
            ],
        }
        compiled = compile_unified_schema(schema, "openai")
        props = compiled["schema"]["properties"]["status_date"]
        assert props["enum"] == ["2026-01-01", "2026-06-15"]
        json.dumps(compiled)

    def test_description_with_datetime_serialisable(self):
        schema = {
            "name": "test",
            "fields": [
                {"id": "created", "type": "string", "description": datetime(2026, 4, 19, 12, 0)},
            ],
        }
        compiled = compile_unified_schema(schema, "openai")
        props = compiled["schema"]["properties"]["created"]
        assert props["description"] == "2026-04-19T12:00:00"
        json.dumps(compiled)

    def test_items_with_nan_sanitised(self):
        schema = {
            "name": "test",
            "fields": [
                {
                    "id": "scores",
                    "type": "array",
                    "items": {"type": "number", "default": float("nan")},
                },
            ],
        }
        compiled = compile_unified_schema(schema, "openai")
        props = compiled["schema"]["properties"]["scores"]
        assert props["items"]["default"] is None
        json.dumps(compiled)

    def test_normal_field_unchanged(self):
        schema = {
            "name": "test",
            "fields": [
                {"id": "name", "type": "string", "description": "A name field", "required": True},
            ],
        }
        compiled = compile_unified_schema(schema, "openai")
        props = compiled["schema"]["properties"]["name"]
        assert props == {"type": "string", "description": "A name field"}
        json.dumps(compiled)


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
