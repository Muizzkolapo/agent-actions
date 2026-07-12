"""Flat schema fields are required by default; opt out with `optional: true`.

Covers both enforcement paths: the vendor compiler (drives the compiled JSON
Schema used by agac/UDF) and the LLM-output validator (drives the
`on_schema_mismatch: reprompt` / reject decision).
"""

from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.validation.schema_output_validator import validate_output_against_schema


def _compiled_required(fields):
    return compile_unified_schema({"name": "s", "fields": fields}, "openai")["schema"]["required"]


# --- Compiler path -----------------------------------------------------------


def test_flat_field_required_by_default():
    assert _compiled_required([{"id": "a", "type": "string"}]) == ["a"]


def test_optional_true_opts_out():
    required = _compiled_required(
        [{"id": "a", "type": "string"}, {"id": "b", "type": "string", "optional": True}]
    )
    assert required == ["a"]


def test_explicit_required_false_opts_out():
    assert _compiled_required([{"id": "a", "type": "string", "required": False}]) == []


def test_explicit_required_true_still_required():
    assert _compiled_required([{"id": "a", "type": "string", "required": True}]) == ["a"]


def test_explicit_required_true_beats_optional_true():
    """A field marked both required: true and optional: true stays required."""
    assert _compiled_required(
        [{"id": "a", "type": "string", "required": True, "optional": True}]
    ) == ["a"]


# --- Validator path (reprompt / reject decision) -----------------------------


def test_omitted_flat_field_is_rejected():
    """Omitting an unmarked flat field is non-compliant, so reprompt fires."""
    schema = {"name": "s", "fields": [{"id": "a"}, {"id": "b"}]}
    report = validate_output_against_schema({"a": "x"}, schema, "act")
    assert not report.is_compliant
    assert "b" in report.missing_required


def test_optional_true_field_omission_accepted():
    schema = {"name": "s", "fields": [{"id": "a"}, {"id": "b", "optional": True}]}
    report = validate_output_against_schema({"a": "x"}, schema, "act")
    assert report.is_compliant
    assert "b" in report.missing_optional


def test_required_false_field_omission_accepted():
    schema = {"name": "s", "fields": [{"id": "a"}, {"id": "b", "required": False}]}
    report = validate_output_against_schema({"a": "x"}, schema, "act")
    assert report.is_compliant
    assert "b" in report.missing_optional


def test_top_level_required_array_still_honored():
    """The existing top-level `required` array behaviour is preserved."""
    schema = {
        "name": "s",
        "required": ["a"],
        "fields": [{"id": "a", "optional": True}, {"id": "b", "required": False}],
    }
    report = validate_output_against_schema({}, schema, "act")
    assert "a" in report.missing_required
    assert "b" not in report.missing_required
