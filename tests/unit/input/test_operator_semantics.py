"""Tests for operator semantics fixes (P2 #4, #7).

Verifies that NOT_* operators return False (not True) on invalid input,
matching the behavior of their positive counterparts.
"""

import pytest

from agent_actions.input.preprocessing.parsing.operators import OPERATORS


class TestNotOperatorsReturnFalseOnInvalidInput:
    """NOT_* operators must return False when the right operand is invalid/None."""

    @pytest.mark.parametrize(
        "op_name,left,right",
        [
            ("NOT_IN", "x", None),
            ("NOT_IN", "x", "not_a_collection"),
            ("NOT_IN", "x", 42),
            ("NOT_CONTAINS", None, "abc"),
            ("NOT_BETWEEN", 5, None),
            ("NOT_BETWEEN", 5, "invalid"),
            ("NOT_BETWEEN", 5, [1]),  # wrong length
        ],
    )
    def test_not_operators_false_on_invalid(self, op_name, left, right):
        result = OPERATORS[op_name](left, right)
        assert result is False, f"{op_name}({left!r}, {right!r}) should be False, got {result}"

    @pytest.mark.parametrize(
        "op_name,left,right",
        [
            ("IN", "x", None),
            ("IN", "x", "not_a_collection"),
            ("CONTAINS", None, "abc"),
            ("BETWEEN", 5, None),
            ("BETWEEN", 5, "invalid"),
            ("BETWEEN", 5, [1]),  # wrong length
        ],
    )
    def test_positive_operators_also_false_on_invalid(self, op_name, left, right):
        result = OPERATORS[op_name](left, right)
        assert result is False, f"{op_name}({left!r}, {right!r}) should be False, got {result}"


class TestNotOperatorsNormalBehavior:
    """NOT_* operators still work correctly for valid inputs."""

    def test_not_in_valid(self):
        assert OPERATORS["NOT_IN"]("x", ["a", "b"]) is True
        assert OPERATORS["NOT_IN"]("a", ["a", "b"]) is False

    def test_not_contains_valid(self):
        assert OPERATORS["NOT_CONTAINS"]("hello world", "xyz") is True
        assert OPERATORS["NOT_CONTAINS"]("hello world", "hello") is False

    def test_not_between_valid(self):
        assert OPERATORS["NOT_BETWEEN"](10, [1, 5]) is True
        assert OPERATORS["NOT_BETWEEN"](3, [1, 5]) is False
