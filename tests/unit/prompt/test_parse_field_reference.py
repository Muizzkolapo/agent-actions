"""Backward-compat safety-net tests for parse_field_reference.

Locks in the exact behavior of parse_field_reference() before the
wrapper refactor (spec 122). These tests must pass identically before
AND after parse_field_reference delegates to ReferenceParser.
"""

import pytest

from agent_actions.prompt.context.scope_parsing import parse_field_reference


# ---------------------------------------------------------------------------
# Happy path — valid references
# ---------------------------------------------------------------------------
class TestParseFieldReferenceValid:
    """Valid field references return (action_name, field_name) tuples."""

    def test_simple_ref(self):
        assert parse_field_reference("action.field") == ("action", "field")

    def test_nested_ref_preserves_after_first_dot(self):
        assert parse_field_reference("action.nested.path") == ("action", "nested.path")

    def test_wildcard_ref(self):
        assert parse_field_reference("action.*") == ("action", "*")

    def test_underscores_in_names(self):
        assert parse_field_reference("my_action.my_field") == ("my_action", "my_field")

    def test_numeric_in_names(self):
        assert parse_field_reference("action1.field2") == ("action1", "field2")

    def test_field_with_special_chars(self):
        assert parse_field_reference("action.field-name") == ("action", "field-name")


# ---------------------------------------------------------------------------
# Error cases — ValueError on malformed input
# ---------------------------------------------------------------------------
class TestParseFieldReferenceErrors:
    """Malformed input raises ValueError with descriptive message."""

    def test_none_raises(self):
        with pytest.raises(ValueError, match="Invalid field reference"):
            parse_field_reference(None)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid field reference"):
            parse_field_reference("")

    def test_no_dot_raises(self):
        with pytest.raises(ValueError, match="Invalid field reference"):
            parse_field_reference("nodot")

    def test_trailing_dot_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_field_reference("action.")

    def test_leading_dot_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_field_reference(".field")

    def test_just_dot_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            parse_field_reference(".")

    def test_non_string_int_raises(self):
        with pytest.raises(ValueError, match="Invalid field reference"):
            parse_field_reference(42)

    def test_non_string_list_raises(self):
        with pytest.raises(ValueError, match="Invalid field reference"):
            parse_field_reference(["action", "field"])
