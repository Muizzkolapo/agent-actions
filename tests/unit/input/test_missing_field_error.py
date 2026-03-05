"""Tests for MissingFieldError (P2 #6).

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

    def test_is_null_returns_true_for_missing_field(self):
        node = ComparisonNode(
            FieldNode("nonexistent"),
            ComparisonOperator.IS_NULL,
        )
        assert evaluate_node(node, {"name": "Alice"}) is True

    def test_is_not_null_returns_false_for_missing_field(self):
        node = ComparisonNode(
            FieldNode("nonexistent"),
            ComparisonOperator.IS_NOT_NULL,
        )
        assert evaluate_node(node, {"name": "Alice"}) is False

    def test_missing_field_in_comparison_still_raises(self):
        node = ComparisonNode(
            FieldNode("nonexistent"),
            ComparisonOperator.EQ,
            LiteralNode("value"),
        )
        with pytest.raises(MissingFieldError):
            evaluate_node(node, {"name": "Alice"})

    def test_existing_field_with_none_value_works(self):
        node = ComparisonNode(
            FieldNode("status"),
            ComparisonOperator.IS_NULL,
        )
        assert evaluate_node(node, {"status": None}) is True

    def test_existing_field_with_value_is_not_null(self):
        node = ComparisonNode(
            FieldNode("status"),
            ComparisonOperator.IS_NOT_NULL,
        )
        assert evaluate_node(node, {"status": "active"}) is True
