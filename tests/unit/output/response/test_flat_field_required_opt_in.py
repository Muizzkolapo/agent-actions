"""Flat schema fields are optional by default; required-by-default is opt-in.

A field in a flat ``fields:`` list is optional unless the schema sets
``required_by_default: true`` (the opt-in) or the field is explicitly marked
(``required: true/false`` or ``optional: true/false``). Covers both enforcement
paths: the vendor compiler (compiled JSON Schema for agac/UDF) and the
LLM-output validator (the ``on_schema_mismatch`` reprompt/reject decision).
"""

from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.validation.schema_output_validator import validate_output_against_schema


def _compiled_required(fields, **schema):
    unified = {"name": "s", "fields": fields, **schema}
    return compile_unified_schema(unified, "openai")["schema"]["required"]


# --- Compiler path: optional by default -------------------------------------


def test_unmarked_flat_field_optional_by_default():
    assert _compiled_required([{"id": "a", "type": "string"}]) == []


def test_required_by_default_flag_makes_unmarked_required():
    assert _compiled_required([{"id": "a", "type": "string"}], required_by_default=True) == ["a"]


def test_flag_on_optional_true_still_opts_out():
    assert _compiled_required(
        [{"id": "a", "type": "string"}, {"id": "b", "type": "string", "optional": True}],
        required_by_default=True,
    ) == ["a"]


def test_explicit_required_true_wins_without_flag():
    assert _compiled_required([{"id": "a", "type": "string", "required": True}]) == ["a"]


def test_explicit_optional_false_is_required_without_flag():
    assert _compiled_required([{"id": "a", "type": "string", "optional": False}]) == ["a"]


def test_explicit_required_false_optional_even_under_flag():
    assert (
        _compiled_required(
            [{"id": "a", "type": "string", "required": False}], required_by_default=True
        )
        == []
    )


def test_explicit_required_true_beats_optional_true():
    assert _compiled_required(
        [{"id": "a", "type": "string", "required": True, "optional": True}]
    ) == ["a"]


# --- Validator path (reprompt / reject decision) -----------------------------


def test_unmarked_omission_accepted_by_default():
    schema = {"name": "s", "fields": [{"id": "a"}, {"id": "b"}]}
    report = validate_output_against_schema({"a": "x"}, schema, "act")
    assert report.is_compliant
    assert "b" in report.missing_optional


def test_unmarked_omission_rejected_under_flag():
    schema = {"name": "s", "required_by_default": True, "fields": [{"id": "a"}, {"id": "b"}]}
    report = validate_output_against_schema({"a": "x"}, schema, "act")
    assert not report.is_compliant
    assert "b" in report.missing_required


def test_optional_true_omission_accepted_under_flag():
    schema = {
        "name": "s",
        "required_by_default": True,
        "fields": [{"id": "a"}, {"id": "b", "optional": True}],
    }
    report = validate_output_against_schema({"a": "x"}, schema, "act")
    assert report.is_compliant
    assert "b" in report.missing_optional


def test_top_level_required_array_still_honored():
    schema = {
        "name": "s",
        "required": ["a"],
        "fields": [{"id": "a", "optional": True}, {"id": "b", "required": False}],
    }
    report = validate_output_against_schema({}, schema, "act")
    assert "a" in report.missing_required
    assert "b" not in report.missing_required
