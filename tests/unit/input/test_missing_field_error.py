"""Tests for MissingFieldError.

Verifies that:
- MissingFieldError is raised for missing fields (not generic ValueError)
- IS_NULL/IS_NOT_NULL handle missing fields correctly
- Other ValueErrors still propagate
"""

import pytest

from agent_actions.input.preprocessing.parsing.ast_nodes import (
    ComparisonNode,
    ComparisonOperator,
    FieldNode,
    LiteralNode,
    MissingFieldError,
    evaluate_node,
)


class TestMissingFieldError:
    def test_is_subclass_of_value_error(self):
        assert issubclass(MissingFieldError, ValueError)

    def test_missing_field_raises_missing_field_error(self):
        node = FieldNode("nonexistent")
        with pytest.raises(MissingFieldError, match="does not exist"):
            evaluate_node(node, {"name": "Alice"})

    @pytest.mark.parametrize(
        ("field", "operator", "data", "expected"),
        [
            pytest.param(
                "nonexistent",
                ComparisonOperator.IS_NULL,
                {"name": "Alice"},
                True,
                id="missing-is-null",
            ),
            pytest.param(
                "nonexistent",
                ComparisonOperator.IS_NOT_NULL,
                {"name": "Alice"},
                False,
                id="missing-is-not-null",
            ),
            pytest.param(
                "status",
                ComparisonOperator.IS_NULL,
                {"status": None},
                True,
                id="present-none-is-null",
            ),
            pytest.param(
                "status",
                ComparisonOperator.IS_NOT_NULL,
                {"status": "active"},
                True,
                id="present-value-is-not-null",
            ),
        ],
    )
    def test_null_check(self, field, operator, data, expected):
        assert evaluate_node(ComparisonNode(FieldNode(field), operator), data) is expected

    def test_missing_field_in_comparison_still_raises(self):
        node = ComparisonNode(
            FieldNode("nonexistent"),
            ComparisonOperator.EQ,
            LiteralNode("value"),
        )
        with pytest.raises(MissingFieldError):
            evaluate_node(node, {"name": "Alice"})

    def test_missing_field_suggests_dot_notation(self):
        """When a field exists as a sub-field, the error message suggests dot notation."""
        node = FieldNode("severity")
        data = {
            "assess_severity": {"severity": "high"},
            "source": {"text": "test"},
        }
        with pytest.raises(MissingFieldError, match=r"Did you mean: assess_severity\.severity\?"):
            evaluate_node(node, data)

    def test_missing_field_multiple_suggestions(self):
        """When a field exists in multiple top-level dicts, all are suggested."""
        node = FieldNode("name")
        data = {
            "action_a": {"name": "Alice"},
            "action_b": {"name": "Bob"},
            "source": {"text": "test"},
        }
        with pytest.raises(MissingFieldError, match=r"action_a\.name.*action_b\.name"):
            evaluate_node(node, data)

    def test_missing_field_no_suggestion_when_not_sub_field(self):
        """When the field doesn't exist anywhere, no suggestion is shown."""
        node = FieldNode("nonexistent")
        data = {
            "assess_severity": {"severity": "high"},
            "source": {"text": "test"},
        }
        with pytest.raises(MissingFieldError, match="does not exist") as exc_info:
            evaluate_node(node, data)
        assert "Did you mean" not in str(exc_info.value)
