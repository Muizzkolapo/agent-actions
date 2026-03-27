"""
Tests for the flat operators module.

Tests all comparison, logical, and function operators via the OPERATORS
and FUNCTIONS dicts, plus the list_operators/get_operator_info shims.
"""

import pytest

from agent_actions.input.preprocessing.parsing.operators import (
    FUNCTIONS,
    OPERATOR_INFO,
    OPERATORS,
    OperatorType,
    get_operator_info,
    list_operators,
)

# -- Equality ------------------------------------------------------------------


class TestEqualityOperators:
    def test_equal_operator(self):
        assert OPERATORS["EQ"](5, 5) is True
        assert OPERATORS["EQ"](5, 10) is False

    def test_not_equal_operator(self):
        assert OPERATORS["NE"](5, 10) is True
        assert OPERATORS["NE"](5, 5) is False


# -- Relational ----------------------------------------------------------------


class TestRelationalOperators:
    def test_basic_comparisons(self):
        assert OPERATORS["LT"](5, 10) is True
        assert OPERATORS["LT"](5, 5) is False
        assert OPERATORS["LE"](5, 5) is True
        assert OPERATORS["LE"](10, 5) is False
        assert OPERATORS["GT"](10, 5) is True
        assert OPERATORS["GT"](5, 5) is False
        assert OPERATORS["GE"](5, 5) is True
        assert OPERATORS["GE"](5, 10) is False

    def test_type_error_returns_false(self):
        for op_name in ("LT", "LE", "GT", "GE"):
            assert OPERATORS[op_name]("test", 5) is False


# -- Array / membership --------------------------------------------------------


class TestArrayOperators:
    def test_in_operator(self):
        assert OPERATORS["IN"](5, [1, 2, 3, 4, 5]) is True
        assert OPERATORS["IN"](6, [1, 2, 3, 4, 5]) is False
        assert OPERATORS["IN"](5, "not_a_list") is False

    def test_not_in_operator(self):
        assert OPERATORS["NOT_IN"](6, [1, 2, 3, 4, 5]) is True
        assert OPERATORS["NOT_IN"](5, [1, 2, 3, 4, 5]) is False
        assert OPERATORS["NOT_IN"](5, "not_a_list") is False  # invalid input → False


# -- String / contains ---------------------------------------------------------


class TestStringOperators:
    def test_contains_operator(self):
        assert OPERATORS["CONTAINS"]("hello world", "world") is True
        assert OPERATORS["CONTAINS"]("hello world", "universe") is False
        assert OPERATORS["CONTAINS"](None, "test") is False
        assert OPERATORS["CONTAINS"](12345, 234) is True  # numeric conversion

    def test_not_contains_operator(self):
        assert OPERATORS["NOT_CONTAINS"]("hello world", "universe") is True
        assert OPERATORS["NOT_CONTAINS"]("hello world", "world") is False


# -- LIKE (SQL pattern matching -> regex) --------------------------------------


class TestLikeOperator:
    @pytest.mark.parametrize(
        "text,pattern,expected",
        [
            ("hello world", "%world", True),
            ("hello world", "hello%", True),
            ("hello world", "hello_world", True),
            ("TEST", "test", True),  # case insensitive
            ("hello", "goodbye", False),
        ],
    )
    def test_like_operator_patterns(self, text, pattern, expected):
        assert OPERATORS["LIKE"](text, pattern) == expected

    def test_like_operator_null_and_special(self):
        assert OPERATORS["LIKE"](None, "%test%") is False
        assert OPERATORS["LIKE"]("test", None) is False
        assert OPERATORS["LIKE"]("test.txt", "%.txt") is True  # regex chars escaped

    def test_not_like_operator(self):
        assert OPERATORS["NOT_LIKE"]("hello", "%world%") is True
        assert OPERATORS["NOT_LIKE"]("hello world", "%world%") is False


# -- BETWEEN -------------------------------------------------------------------


class TestBetweenOperator:
    def test_between_operator(self):
        assert OPERATORS["BETWEEN"](5, [1, 10]) is True
        assert OPERATORS["BETWEEN"](1, [1, 10]) is True  # inclusive lower
        assert OPERATORS["BETWEEN"](10, [1, 10]) is True  # inclusive upper
        assert OPERATORS["BETWEEN"](0, [1, 10]) is False

    def test_between_operator_invalid_inputs(self):
        assert OPERATORS["BETWEEN"](5, "not_a_list") is False
        assert OPERATORS["BETWEEN"](5, [1]) is False
        assert OPERATORS["BETWEEN"]("test", [1, 10]) is False  # type mismatch

    def test_not_between_operator(self):
        assert OPERATORS["NOT_BETWEEN"](0, [1, 10]) is True
        assert OPERATORS["NOT_BETWEEN"](5, [1, 10]) is False


# -- NULL ----------------------------------------------------------------------


class TestNullOperators:
    def test_is_null_operator(self):
        assert OPERATORS["IS_NULL"](None) is True
        assert OPERATORS["IS_NULL"](0) is False
        assert OPERATORS["IS_NULL"]("") is False

    def test_is_not_null_operator(self):
        assert OPERATORS["IS_NOT_NULL"](None) is False
        assert OPERATORS["IS_NOT_NULL"](0) is True


# -- Functions -----------------------------------------------------------------


class TestFunctionOperators:
    def test_length_function(self):
        assert FUNCTIONS["LENGTH"](["hello"]) == 5
        assert FUNCTIONS["LENGTH"]([None]) == 0

    def test_length_function_invalid_args(self):
        with pytest.raises(ValueError, match="LENGTH function requires exactly 1 argument"):
            FUNCTIONS["LENGTH"]([])

    def test_string_functions(self):
        assert FUNCTIONS["UPPER"](["hello"]) == "HELLO"
        assert FUNCTIONS["LOWER"](["HELLO"]) == "hello"
        assert FUNCTIONS["TRIM"](["  hello  "]) == "hello"


# -- Operator Info / Shims -----------------------------------------------------


class TestOperatorInfo:
    def test_get_operator_info(self):
        info = get_operator_info("EQ")
        assert info is not None
        assert info.name == "EQ"
        assert info.symbol == "=="
        assert info.operator_type == OperatorType.COMPARISON

    def test_get_operator_info_missing(self):
        assert get_operator_info("UNKNOWN") is None

    def test_list_operators_filtered(self):
        comparison_ops = list_operators(OperatorType.COMPARISON)
        assert all(op.operator_type == OperatorType.COMPARISON for op in comparison_ops)
        assert len(comparison_ops) > 0

    def test_list_operators_all(self):
        all_ops = list_operators()
        assert len(all_ops) == len(OPERATOR_INFO)

    def test_all_operators_have_info(self):
        """Every OPERATORS entry has a matching OPERATOR_INFO entry."""
        for name in OPERATORS:
            assert name in OPERATOR_INFO, f"Missing OPERATOR_INFO for {name}"
