"""G-5/J-3: Coverage of prompt/context/scope_parsing.py — parse_field_reference and friends."""

import pytest

from agent_actions.prompt.context.scope_parsing import (
    extract_field_value,
    parse_field_reference,
)


class TestParseFieldReference:
    """parse_field_reference: 'action.field' format parsing."""

    def test_simple_dotted_reference(self):
        action, field = parse_field_reference("my_action.my_field")
        assert action == "my_action"
        assert field == "my_field"

    def test_field_prefix_pattern_returns_sentinel(self):
        """References ending with '_' (no dot) are field prefix patterns."""
        action, field = parse_field_reference("extract_qa_")
        assert action == "extract_qa"
        assert field == "_"

    def test_invalid_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid field reference"):
            parse_field_reference("")

    def test_invalid_none_raises(self):
        with pytest.raises((ValueError, AttributeError)):
            parse_field_reference(None)  # type: ignore[arg-type]

    def test_no_dot_no_underscore_raises(self):
        with pytest.raises(ValueError, match="Invalid field reference"):
            parse_field_reference("justword")

    def test_empty_action_name_raises(self):
        with pytest.raises(ValueError, match="Invalid field reference"):
            parse_field_reference(".field")

    def test_empty_field_name_raises(self):
        with pytest.raises(ValueError, match="Invalid field reference"):
            parse_field_reference("action.")

    def test_underscore_only_raises(self):
        """A lone '_' has an empty base name — must raise."""
        with pytest.raises(ValueError):
            parse_field_reference("_")

    def test_multiple_dots_splits_on_first(self):
        """split('.', 1) means extra dots become part of the field name."""
        action, field = parse_field_reference("action.field.sub")
        assert action == "action"
        assert field == "field.sub"


class TestExtractFieldValue:
    """extract_field_value: field_context[action_name][field_name] lookup."""

    def test_simple_lookup(self):
        ctx = {"my_action": {"name": "Alice"}}
        assert extract_field_value(ctx, "my_action", "name") == "Alice"

    def test_missing_action_returns_default(self):
        ctx = {"other": {"name": "Alice"}}
        result = extract_field_value(ctx, "my_action", "name")
        assert result is None

    def test_missing_field_returns_default(self):
        ctx = {"my_action": {"name": "Alice"}}
        result = extract_field_value(ctx, "my_action", "missing")
        assert result is None

    def test_custom_default(self):
        ctx = {}
        result = extract_field_value(ctx, "a", "b", default="fallback")
        assert result == "fallback"

    def test_none_context_returns_default(self):
        result = extract_field_value(None, "action", "field")  # type: ignore[arg-type]
        assert result is None

    def test_nested_dotted_field_path(self):
        ctx = {"action": {"meta": {"score": 0.9}}}
        result = extract_field_value(ctx, "action", "meta.score")
        assert result == 0.9

    def test_integer_value(self):
        ctx = {"action": {"count": 5}}
        assert extract_field_value(ctx, "action", "count") == 5

    def test_false_value(self):
        ctx = {"action": {"flag": False}}
        assert extract_field_value(ctx, "action", "flag") is False
