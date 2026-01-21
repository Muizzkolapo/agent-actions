"""
Tests for the operator registry system.

Tests the extensible operator registry for WHERE clause processing,
including built-in operators, custom operators, and operator evaluation.
"""

import pytest
import re
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
    OperatorInfo,
)


class TestOperatorInfo:
    """Test OperatorInfo dataclass."""

    def test_operator_info_creation(self):
        """Test creating an OperatorInfo instance."""
        info = OperatorInfo(
            name="EQ",
            symbol="==",
            operator_type=OperatorType.COMPARISON,
            precedence=7,
            associativity="left",
            arity=2,
            description="Equality comparison",
        )

        assert info.name == "EQ"
        assert info.symbol == "=="
        assert info.operator_type == OperatorType.COMPARISON
        assert info.precedence == 7
        assert info.associativity == "left"
        assert info.arity == 2
        assert info.description == "Equality comparison"


class TestEqualityOperators:
    """Test equality comparison operators."""

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (5, 5, True),
            (5, 10, False),
            ("test", "test", True),
            ("test", "TEST", False),
            (None, None, True),
            (None, 5, False),
            (True, True, True),
            (True, False, False),
            ([1, 2], [1, 2], True),
            ([1, 2], [2, 1], False),
        ],
    )
    def test_equal_operator(self, left, right, expected):
        """Test EqualOperator evaluation."""
        op = EqualOperator()
        result = op.evaluate(left, right)
        assert result == expected

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (5, 10, True),
            (5, 5, False),
            ("test", "TEST", True),
            ("test", "test", False),
            (None, 5, True),
            (None, None, False),
        ],
    )
    def test_not_equal_operator(self, left, right, expected):
        """Test NotEqualOperator evaluation."""
        op = NotEqualOperator()
        result = op.evaluate(left, right)
        assert result == expected


class TestRelationalOperators:
    """Test relational comparison operators (<, <=, >, >=)."""

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (5, 10, True),
            (10, 5, False),
            (5, 5, False),
            (3.14, 3.15, True),
            ("a", "b", True),
            ("b", "a", False),
        ],
    )
    def test_less_than_operator(self, left, right, expected):
        """Test LessThanOperator evaluation."""
        op = LessThanOperator()
        result = op.evaluate(left, right)
        assert result == expected

    def test_less_than_type_error(self):
        """Test LessThanOperator handles type errors gracefully."""
        op = LessThanOperator()
        # Comparing string to number should return False
        result = op.evaluate("test", 5)
        assert result is False

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (5, 10, True),
            (10, 5, False),
            (5, 5, True),
            (3.14, 3.15, True),
        ],
    )
    def test_less_equal_operator(self, left, right, expected):
        """Test LessEqualOperator evaluation."""
        op = LessEqualOperator()
        result = op.evaluate(left, right)
        assert result == expected

    def test_less_equal_type_error(self):
        """Test LessEqualOperator handles type errors gracefully."""
        op = LessEqualOperator()
        result = op.evaluate("test", 5)
        assert result is False

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (10, 5, True),
            (5, 10, False),
            (5, 5, False),
            (3.15, 3.14, True),
        ],
    )
    def test_greater_than_operator(self, left, right, expected):
        """Test GreaterThanOperator evaluation."""
        op = GreaterThanOperator()
        result = op.evaluate(left, right)
        assert result == expected

    def test_greater_than_type_error(self):
        """Test GreaterThanOperator handles type errors gracefully."""
        op = GreaterThanOperator()
        result = op.evaluate("test", 5)
        assert result is False

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (10, 5, True),
            (5, 10, False),
            (5, 5, True),
            (3.15, 3.14, True),
        ],
    )
    def test_greater_equal_operator(self, left, right, expected):
        """Test GreaterEqualOperator evaluation."""
        op = GreaterEqualOperator()
        result = op.evaluate(left, right)
        assert result == expected

    def test_greater_equal_type_error(self):
        """Test GreaterEqualOperator handles type errors gracefully."""
        op = GreaterEqualOperator()
        result = op.evaluate("test", 5)
        assert result is False


class TestArrayOperators:
    """Test array/list operators (IN, NOT IN)."""

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (5, [1, 2, 3, 4, 5], True),
            (6, [1, 2, 3, 4, 5], False),
            ("apple", ["apple", "banana", "cherry"], True),
            ("grape", ["apple", "banana", "cherry"], False),
            (5, (1, 2, 3, 4, 5), True),
            (5, {1, 2, 3, 4, 5}, True),
        ],
    )
    def test_in_operator(self, left, right, expected):
        """Test InOperator evaluation."""
        op = InOperator()
        result = op.evaluate(left, right)
        assert result == expected

    def test_in_operator_invalid_right_type(self):
        """Test InOperator with invalid right operand type."""
        op = InOperator()
        result = op.evaluate(5, "not_a_list")
        assert result is False

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (6, [1, 2, 3, 4, 5], True),
            (5, [1, 2, 3, 4, 5], False),
            ("grape", ["apple", "banana", "cherry"], True),
            ("apple", ["apple", "banana", "cherry"], False),
        ],
    )
    def test_not_in_operator(self, left, right, expected):
        """Test NotInOperator evaluation."""
        op = NotInOperator()
        result = op.evaluate(left, right)
        assert result == expected

    def test_not_in_operator_invalid_right_type(self):
        """Test NotInOperator with invalid right operand type."""
        op = NotInOperator()
        result = op.evaluate(5, "not_a_list")
        assert result is True


class TestStringOperators:
    """Test string operators (CONTAINS, NOT CONTAINS)."""

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            ("hello world", "world", True),
            ("hello world", "WORLD", False),  # Case-sensitive
            ("hello world", "universe", False),
            ("test123", "123", True),
            ("", "test", False),
        ],
    )
    def test_contains_operator(self, left, right, expected):
        """Test ContainsOperator evaluation (case-sensitive)."""
        op = ContainsOperator()
        result = op.evaluate(left, right)
        assert result == expected

    def test_contains_operator_null_left(self):
        """Test ContainsOperator with None left operand."""
        op = ContainsOperator()
        result = op.evaluate(None, "test")
        assert result is False

    def test_contains_operator_numeric_conversion(self):
        """Test ContainsOperator converts numbers to strings."""
        op = ContainsOperator()
        result = op.evaluate(12345, 234)
        assert result is True

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            ("hello world", "universe", True),
            ("hello world", "world", False),
            ("test123", "456", True),
        ],
    )
    def test_not_contains_operator(self, left, right, expected):
        """Test NotContainsOperator evaluation."""
        op = NotContainsOperator()
        result = op.evaluate(left, right)
        assert result == expected

    def test_not_contains_operator_null_left(self):
        """Test NotContainsOperator with None left operand."""
        op = NotContainsOperator()
        result = op.evaluate(None, "test")
        assert result is True


class TestLikeOperator:
    """Test SQL LIKE pattern matching operator."""

    @pytest.mark.parametrize(
        "text,pattern,expected",
        [
            ("hello world", "%world", True),
            ("hello world", "hello%", True),
            ("hello world", "%llo%", True),
            ("hello world", "hello_world", True),
            ("hello world", "hello_____", False),
            ("test", "test", True),
            ("TEST", "test", True),  # Case insensitive
            ("hello", "goodbye", False),
            ("abc123def", "%123%", True),
            ("abc123def", "abc%def", True),
        ],
    )
    def test_like_operator_basic(self, text, pattern, expected):
        """Test LikeOperator basic pattern matching."""
        op = LikeOperator()
        result = op.evaluate(text, pattern)
        assert result == expected

    def test_like_operator_null_handling(self):
        """Test LikeOperator with None values."""
        op = LikeOperator()
        assert op.evaluate(None, "%test%") is False
        assert op.evaluate("test", None) is False
        assert op.evaluate(None, None) is False

    def test_like_operator_special_chars(self):
        """Test LikeOperator escapes special regex characters."""
        op = LikeOperator()
        # Dots should be treated as literal dots, not regex wildcards
        result = op.evaluate("test.txt", "%.txt")
        assert result is True

    def test_not_like_operator(self):
        """Test NotLikeOperator evaluation."""
        op = NotLikeOperator()
        assert op.evaluate("hello", "%world%") is True
        assert op.evaluate("hello world", "%world%") is False


class TestBetweenOperator:
    """Test BETWEEN range operator."""

    @pytest.mark.parametrize(
        "value,range_vals,expected",
        [
            (5, [1, 10], True),
            (1, [1, 10], True),
            (10, [1, 10], True),
            (0, [1, 10], False),
            (11, [1, 10], False),
            (5.5, [1.0, 10.0], True),
            ("m", ["a", "z"], True),
            ("a", ["a", "z"], True),
            ("z", ["a", "z"], True),
        ],
    )
    def test_between_operator_basic(self, value, range_vals, expected):
        """Test BetweenOperator basic evaluation."""
        op = BetweenOperator()
        result = op.evaluate(value, range_vals)
        assert result == expected

    def test_between_operator_invalid_range(self):
        """Test BetweenOperator with invalid range."""
        op = BetweenOperator()
        # Not a list
        assert op.evaluate(5, "not_a_list") is False
        # Not exactly 2 elements
        assert op.evaluate(5, [1]) is False
        assert op.evaluate(5, [1, 2, 3]) is False

    def test_between_operator_type_error(self):
        """Test BetweenOperator with incompatible types."""
        op = BetweenOperator()
        result = op.evaluate("test", [1, 10])
        assert result is False

    def test_not_between_operator(self):
        """Test NotBetweenOperator evaluation."""
        op = NotBetweenOperator()
        assert op.evaluate(0, [1, 10]) is True
        assert op.evaluate(5, [1, 10]) is False


class TestNullOperators:
    """Test NULL checking operators."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, True),
            (0, False),
            ("", False),
            ([], False),
            (False, False),
        ],
    )
    def test_is_null_operator(self, value, expected):
        """Test IsNullOperator evaluation."""
        op = IsNullOperator()
        result = op.evaluate(value)
        assert result == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            (None, False),
            (0, True),
            ("", True),
            ([], True),
            (False, True),
        ],
    )
    def test_is_not_null_operator(self, value, expected):
        """Test IsNotNullOperator evaluation."""
        op = IsNotNullOperator()
        result = op.evaluate(value)
        assert result == expected


class TestLogicalOperators:
    """Test logical operators (AND, OR, NOT)."""

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
            (1, 1, True),
            (0, 1, False),
        ],
    )
    def test_and_operator(self, left, right, expected):
        """Test AndOperator evaluation."""
        op = AndOperator()
        result = op.evaluate(left, right)
        assert result == expected

    @pytest.mark.parametrize(
        "left,right,expected",
        [
            (True, True, True),
            (True, False, True),
            (False, True, True),
            (False, False, False),
            (1, 0, True),
            (0, 0, False),
        ],
    )
    def test_or_operator(self, left, right, expected):
        """Test OrOperator evaluation."""
        op = OrOperator()
        result = op.evaluate(left, right)
        assert result == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, False),
            (False, True),
            (1, False),
            (0, True),
            (None, True),
            ("", True),
            ("test", False),
        ],
    )
    def test_not_operator(self, value, expected):
        """Test NotOperator evaluation."""
        op = NotOperator()
        result = op.evaluate(value)
        assert result == expected


class TestFunctionOperators:
    """Test function operators (LENGTH, UPPER, LOWER, TRIM)."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("hello", 5),
            ([1, 2, 3], 3),
            ((1, 2), 2),
            ({"a": 1, "b": 2}, 2),
            (None, 0),
            ("", 0),
        ],
    )
    def test_length_function(self, value, expected):
        """Test LengthFunction evaluation."""
        func = LengthFunction()
        result = func.evaluate_function([value])
        assert result == expected

    def test_length_function_invalid_args(self):
        """Test LengthFunction with invalid number of arguments."""
        func = LengthFunction()
        with pytest.raises(ValueError, match="LENGTH function requires exactly 1 argument"):
            func.evaluate_function([])
        with pytest.raises(ValueError, match="LENGTH function requires exactly 1 argument"):
            func.evaluate_function([1, 2])

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("hello", "HELLO"),
            ("HELLO", "HELLO"),
            ("HeLLo", "HELLO"),
            (None, ""),
            (123, "123"),
        ],
    )
    def test_upper_function(self, value, expected):
        """Test UpperFunction evaluation."""
        func = UpperFunction()
        result = func.evaluate_function([value])
        assert result == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("HELLO", "hello"),
            ("hello", "hello"),
            ("HeLLo", "hello"),
            (None, ""),
            (123, "123"),
        ],
    )
    def test_lower_function(self, value, expected):
        """Test LowerFunction evaluation."""
        func = LowerFunction()
        result = func.evaluate_function([value])
        assert result == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("  hello  ", "hello"),
            ("hello", "hello"),
            ("\thello\n", "hello"),
            ("  ", ""),
            (None, ""),
        ],
    )
    def test_trim_function(self, value, expected):
        """Test TrimFunction evaluation."""
        func = TrimFunction()
        result = func.evaluate_function([value])
        assert result == expected


class TestOperatorRegistry:
    """Test operator registry management."""

    @pytest.fixture
    def registry(self):
        """Create a fresh operator registry."""
        return OperatorRegistry()

    def test_registry_initialization(self, registry):
        """Test registry is initialized with built-in operators."""
        # Should have comparison operators
        assert registry.get_operator("EQ") is not None
        assert registry.get_operator("NE") is not None
        assert registry.get_operator("LT") is not None

        # Should have logical operators
        assert registry.get_operator("AND") is not None
        assert registry.get_operator("OR") is not None

        # Should have function operators
        assert registry.get_operator("LENGTH") is not None

    def test_get_operator_by_name(self, registry):
        """Test retrieving operators by name."""
        op = registry.get_operator("EQ")
        assert op is not None
        assert isinstance(op, EqualOperator)

    def test_get_operator_by_symbol(self, registry):
        """Test retrieving operators by symbol."""
        op = registry.get_operator("==")
        assert op is not None
        assert isinstance(op, EqualOperator)

    def test_get_operator_unknown(self, registry):
        """Test retrieving unknown operator returns None."""
        op = registry.get_operator("UNKNOWN")
        assert op is None

    def test_get_operator_info(self, registry):
        """Test getting operator information."""
        info = registry.get_operator_info("EQ")
        assert info is not None
        assert info.name == "EQ"
        assert info.symbol == "=="
        assert info.operator_type == OperatorType.COMPARISON

    def test_list_operators(self, registry):
        """Test listing all operators."""
        operators = registry.list_operators()
        assert len(operators) > 0
        # Should have at least 16 comparison operators
        comparison_ops = [op for op in operators if op.operator_type == OperatorType.COMPARISON]
        assert len(comparison_ops) >= 16

    def test_list_operators_filtered(self, registry):
        """Test listing operators filtered by type."""
        comparison_ops = registry.list_operators(OperatorType.COMPARISON)
        logical_ops = registry.list_operators(OperatorType.LOGICAL)
        function_ops = registry.list_operators(OperatorType.FUNCTION)

        assert all(op.operator_type == OperatorType.COMPARISON for op in comparison_ops)
        assert all(op.operator_type == OperatorType.LOGICAL for op in logical_ops)
        assert all(op.operator_type == OperatorType.FUNCTION for op in function_ops)


class TestGlobalRegistry:
    """Test global registry singleton."""

    def test_get_global_registry(self):
        """Test getting global registry instance."""
        registry1 = get_global_registry()
        registry2 = get_global_registry()

        # Should be the same instance
        assert registry1 is registry2

    def test_global_registry_has_operators(self):
        """Test global registry is pre-populated with operators."""
        registry = get_global_registry()
        operators = registry.list_operators()
        assert len(operators) > 0


class TestOperatorEdgeCases:
    """Test edge cases and error handling."""

    def test_comparison_with_mixed_types(self):
        """Test comparisons handle mixed types gracefully."""
        op = LessThanOperator()
        # Should return False instead of raising TypeError
        assert op.evaluate("string", 123) is False
        assert op.evaluate([1, 2], {"a": 1}) is False

    def test_null_in_comparisons(self):
        """Test NULL values in various operators."""
        eq_op = EqualOperator()
        assert eq_op.evaluate(None, None) is True
        assert eq_op.evaluate(None, 5) is False

        lt_op = LessThanOperator()
        # None comparisons should fail gracefully
        result = lt_op.evaluate(None, 5)
        # Result depends on Python's None comparison behavior
        assert isinstance(result, bool)

    def test_empty_values(self):
        """Test operators with empty values."""
        contains_op = ContainsOperator()
        assert contains_op.evaluate("", "test") is False
        assert contains_op.evaluate("test", "") is True  # Empty string is in any string

        in_op = InOperator()
        assert in_op.evaluate(1, []) is False

    def test_special_characters_in_strings(self):
        """Test string operators with special characters."""
        contains_op = ContainsOperator()
        assert contains_op.evaluate("test@example.com", "@") is True
        assert contains_op.evaluate("price: $10.99", "$") is True

        like_op = LikeOperator()
        # Should escape special regex chars
        assert like_op.evaluate("test.txt", "%.txt") is True
