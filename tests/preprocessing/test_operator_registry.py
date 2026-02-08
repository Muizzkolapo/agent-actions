"""
Tests for the operator registry system.

Tests the extensible operator registry for WHERE clause processing,
including built-in operators, custom operators, and operator evaluation.
"""

import pytest

from agent_actions.input.preprocessing.parsing.operator_registry import (
    OperatorRegistry,
    get_global_registry,
    EqualOperator,
    NotEqualOperator,
    LessThanOperator,
    LessEqualOperator,
    GreaterThanOperator,
    GreaterEqualOperator,
    InOperator,
    NotInOperator,
    ContainsOperator,
    NotContainsOperator,
    LikeOperator,
    NotLikeOperator,
    BetweenOperator,
    NotBetweenOperator,
    IsNullOperator,
    IsNotNullOperator,
    AndOperator,
    OrOperator,
    NotOperator,
    LengthFunction,
    UpperFunction,
    LowerFunction,
    TrimFunction,
    OperatorType,
)


# -- Equality ------------------------------------------------------------------


class TestEqualityOperators:
    def test_equal_operator(self):
        op = EqualOperator()
        assert op.evaluate(5, 5) is True
        assert op.evaluate(5, 10) is False

    def test_not_equal_operator(self):
        op = NotEqualOperator()
        assert op.evaluate(5, 10) is True
        assert op.evaluate(5, 5) is False


# -- Relational ----------------------------------------------------------------


class TestRelationalOperators:
    def test_basic_comparisons(self):
        """Each relational operator returns correct result for clear-cut inputs."""
        assert LessThanOperator().evaluate(5, 10) is True
        assert LessThanOperator().evaluate(5, 5) is False
        assert LessEqualOperator().evaluate(5, 5) is True
        assert LessEqualOperator().evaluate(10, 5) is False
        assert GreaterThanOperator().evaluate(10, 5) is True
        assert GreaterThanOperator().evaluate(5, 5) is False
        assert GreaterEqualOperator().evaluate(5, 5) is True
        assert GreaterEqualOperator().evaluate(5, 10) is False

    def test_type_error_returns_false(self):
        """Relational operators return False on incompatible types instead of raising."""
        for OpClass in (
            LessThanOperator,
            LessEqualOperator,
            GreaterThanOperator,
            GreaterEqualOperator,
        ):
            assert OpClass().evaluate("test", 5) is False


# -- Array / membership --------------------------------------------------------


class TestArrayOperators:
    def test_in_operator(self):
        op = InOperator()
        assert op.evaluate(5, [1, 2, 3, 4, 5]) is True
        assert op.evaluate(6, [1, 2, 3, 4, 5]) is False
        assert op.evaluate(5, "not_a_list") is False

    def test_not_in_operator(self):
        op = NotInOperator()
        assert op.evaluate(6, [1, 2, 3, 4, 5]) is True
        assert op.evaluate(5, [1, 2, 3, 4, 5]) is False
        assert op.evaluate(5, "not_a_list") is True


# -- String / contains ---------------------------------------------------------


class TestStringOperators:
    def test_contains_operator(self):
        op = ContainsOperator()
        assert op.evaluate("hello world", "world") is True
        assert op.evaluate("hello world", "universe") is False
        assert op.evaluate(None, "test") is False
        assert op.evaluate(12345, 234) is True  # numeric conversion

    def test_not_contains_operator(self):
        op = NotContainsOperator()
        assert op.evaluate("hello world", "universe") is True
        assert op.evaluate("hello world", "world") is False


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
        assert LikeOperator().evaluate(text, pattern) == expected

    def test_like_operator_null_and_special(self):
        op = LikeOperator()
        assert op.evaluate(None, "%test%") is False
        assert op.evaluate("test", None) is False
        assert op.evaluate("test.txt", "%.txt") is True  # regex chars escaped

    def test_not_like_operator(self):
        op = NotLikeOperator()
        assert op.evaluate("hello", "%world%") is True
        assert op.evaluate("hello world", "%world%") is False


# -- BETWEEN -------------------------------------------------------------------


class TestBetweenOperator:
    def test_between_operator(self):
        op = BetweenOperator()
        assert op.evaluate(5, [1, 10]) is True
        assert op.evaluate(1, [1, 10]) is True  # inclusive lower
        assert op.evaluate(10, [1, 10]) is True  # inclusive upper
        assert op.evaluate(0, [1, 10]) is False

    def test_between_operator_invalid_inputs(self):
        op = BetweenOperator()
        assert op.evaluate(5, "not_a_list") is False
        assert op.evaluate(5, [1]) is False
        assert op.evaluate("test", [1, 10]) is False  # type mismatch

    def test_not_between_operator(self):
        op = NotBetweenOperator()
        assert op.evaluate(0, [1, 10]) is True
        assert op.evaluate(5, [1, 10]) is False


# -- NULL ----------------------------------------------------------------------


class TestNullOperators:
    def test_is_null_operator(self):
        op = IsNullOperator()
        assert op.evaluate(None) is True
        assert op.evaluate(0) is False
        assert op.evaluate("") is False

    def test_is_not_null_operator(self):
        op = IsNotNullOperator()
        assert op.evaluate(None) is False
        assert op.evaluate(0) is True


# -- Logical -------------------------------------------------------------------


class TestLogicalOperators:
    def test_logical_operators(self):
        """AND, OR, NOT produce expected truth values."""
        assert AndOperator().evaluate(True, True) is True
        assert AndOperator().evaluate(True, False) is False
        assert OrOperator().evaluate(True, False) is True
        assert OrOperator().evaluate(False, False) is False
        assert NotOperator().evaluate(True) is False
        assert NotOperator().evaluate(False) is True


# -- Functions -----------------------------------------------------------------


class TestFunctionOperators:
    def test_length_function(self):
        func = LengthFunction()
        assert func.evaluate_function(["hello"]) == 5
        assert func.evaluate_function([None]) == 0

    def test_length_function_invalid_args(self):
        with pytest.raises(ValueError, match="LENGTH function requires exactly 1 argument"):
            LengthFunction().evaluate_function([])

    def test_string_functions(self):
        """UPPER, LOWER, TRIM produce expected transformations."""
        assert UpperFunction().evaluate_function(["hello"]) == "HELLO"
        assert LowerFunction().evaluate_function(["HELLO"]) == "hello"
        assert TrimFunction().evaluate_function(["  hello  "]) == "hello"


# -- Registry ------------------------------------------------------------------


class TestOperatorRegistry:
    def test_registry_initialization_and_lookup(self):
        """Registry is populated and supports lookup by name and symbol."""
        registry = OperatorRegistry()
        assert isinstance(registry.get_operator("EQ"), EqualOperator)
        assert isinstance(registry.get_operator("=="), EqualOperator)
        assert registry.get_operator("UNKNOWN") is None

    def test_get_operator_info(self):
        registry = OperatorRegistry()
        info = registry.get_operator_info("EQ")
        assert info is not None
        assert info.name == "EQ"
        assert info.symbol == "=="
        assert info.operator_type == OperatorType.COMPARISON

    def test_list_operators_filtered(self):
        registry = OperatorRegistry()
        comparison_ops = registry.list_operators(OperatorType.COMPARISON)
        assert all(op.operator_type == OperatorType.COMPARISON for op in comparison_ops)
        assert len(comparison_ops) > 0

    def test_global_registry_singleton(self):
        assert get_global_registry() is get_global_registry()
