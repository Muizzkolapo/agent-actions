"""
Integration tests for AST nodes and evaluate_node() function.

Tests that all ComparisonOperator enum values work correctly through
the evaluate_node() recursive evaluator.
"""

import pytest

from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser
from agent_actions.input.preprocessing.parsing.ast_nodes import (
    MissingFieldError,
    ComparisonNode,
    ComparisonOperator,
    FieldNode,
    FunctionNode,
    LiteralNode,
    LogicalNode,
    LogicalOperator,
    WhereClauseAST,
    _field_exists,
    evaluate_node,
)


class TestEvaluateNodeIntegration:
    """Integration tests for evaluate_node() with all operators."""

    @pytest.fixture
    def sample_data(self):
        """Sample data for testing."""
        return {
            "name": "John Doe",
            "age": 25,
            "status": "active",
            "score": 85.5,
            "tags": ["python", "javascript", "rust"],
            "email": "john@example.com",
            "balance": None,
            "user": {"id": 123, "role": "admin"},
        }

    # Test all comparison operators through evaluate_node()

    def test_equal_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.EQ, LiteralNode(25))
        assert evaluate_node(node, sample_data) is True

    def test_not_equal_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.NE, LiteralNode(30))
        assert evaluate_node(node, sample_data) is True

    def test_less_than_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.LT, LiteralNode(30))
        assert evaluate_node(node, sample_data) is True

    def test_less_equal_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.LE, LiteralNode(25))
        assert evaluate_node(node, sample_data) is True

    def test_greater_than_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.GT, LiteralNode(20))
        assert evaluate_node(node, sample_data) is True

    def test_greater_equal_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.GE, LiteralNode(25))
        assert evaluate_node(node, sample_data) is True

    def test_in_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.IN, LiteralNode([20, 25, 30]))
        assert evaluate_node(node, sample_data) is True

    def test_not_in_operator_integration(self, sample_data):
        node = ComparisonNode(
            FieldNode("age"), ComparisonOperator.NOT_IN, LiteralNode([10, 15, 20])
        )
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(
            FieldNode("age"), ComparisonOperator.NOT_IN, LiteralNode([20, 25, 30])
        )
        assert evaluate_node(node, sample_data) is False

    def test_contains_operator_integration(self, sample_data):
        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.CONTAINS, LiteralNode("@example.com")
        )
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.CONTAINS, LiteralNode("@gmail.com")
        )
        assert evaluate_node(node, sample_data) is False

    def test_not_contains_operator_integration(self, sample_data):
        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.NOT_CONTAINS, LiteralNode("@gmail.com")
        )
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.NOT_CONTAINS, LiteralNode("@example.com")
        )
        assert evaluate_node(node, sample_data) is False

    def test_like_operator_integration(self, sample_data):
        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.LIKE, LiteralNode("%@example.com")
        )
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(FieldNode("name"), ComparisonOperator.LIKE, LiteralNode("John%"))
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.LIKE, LiteralNode("%@gmail.com")
        )
        assert evaluate_node(node, sample_data) is False

    def test_not_like_operator_integration(self, sample_data):
        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.NOT_LIKE, LiteralNode("%@gmail.com")
        )
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.NOT_LIKE, LiteralNode("%@example.com")
        )
        assert evaluate_node(node, sample_data) is False

    def test_between_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.BETWEEN, LiteralNode([20, 30]))
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.BETWEEN, LiteralNode([30, 40]))
        assert evaluate_node(node, sample_data) is False

    def test_not_between_operator_integration(self, sample_data):
        node = ComparisonNode(
            FieldNode("age"), ComparisonOperator.NOT_BETWEEN, LiteralNode([30, 40])
        )
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(
            FieldNode("age"), ComparisonOperator.NOT_BETWEEN, LiteralNode([20, 30])
        )
        assert evaluate_node(node, sample_data) is False

    def test_is_null_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("balance"), ComparisonOperator.IS_NULL)
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.IS_NULL)
        assert evaluate_node(node, sample_data) is False

    def test_is_not_null_operator_integration(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.IS_NOT_NULL)
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(FieldNode("balance"), ComparisonOperator.IS_NOT_NULL)
        assert evaluate_node(node, sample_data) is False

    # Test nested field access

    def test_nested_field_comparison(self, sample_data):
        node = ComparisonNode(FieldNode("user.id"), ComparisonOperator.EQ, LiteralNode(123))
        assert evaluate_node(node, sample_data) is True

        node = ComparisonNode(FieldNode("user.role"), ComparisonOperator.EQ, LiteralNode("admin"))
        assert evaluate_node(node, sample_data) is True

    # Test edge cases

    def test_type_mismatch_handled_gracefully(self, sample_data):
        """Type mismatches return False, not raise."""
        node = ComparisonNode(FieldNode("name"), ComparisonOperator.GT, LiteralNode(100))
        assert evaluate_node(node, sample_data) is False

    def test_missing_field_raises_value_error(self, sample_data):
        """Missing field raises ValueError instead of silently returning None."""
        node = ComparisonNode(FieldNode("nonexistent"), ComparisonOperator.EQ, LiteralNode("value"))
        with pytest.raises(ValueError, match="does not exist"):
            evaluate_node(node, sample_data)

    def test_null_safety_unary_operator(self, sample_data):
        node = ComparisonNode(FieldNode("balance"), ComparisonOperator.IS_NULL, None)
        assert evaluate_node(node, sample_data) is True

    def test_null_safety_binary_operator_missing_right(self, sample_data):
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.EQ, None)
        with pytest.raises(ValueError, match="requires a right operand"):
            evaluate_node(node, sample_data)

    # Test with full AST evaluation

    def test_full_ast_with_logical_operators(self, sample_data):
        """Test complex AST with logical operators."""
        # age > 20 AND status == 'active'
        ast_node = LogicalNode(
            LogicalOperator.AND,
            ComparisonNode(FieldNode("age"), ComparisonOperator.GT, LiteralNode(20)),
            ComparisonNode(FieldNode("status"), ComparisonOperator.EQ, LiteralNode("active")),
        )
        assert evaluate_node(ast_node, sample_data) is True

    def test_full_ast_complex_expression(self, sample_data):
        """Test complex WHERE clause through full AST."""
        # (age >= 18 AND status == 'active') OR user.role == 'admin'
        ast_root = LogicalNode(
            LogicalOperator.OR,
            LogicalNode(
                LogicalOperator.AND,
                ComparisonNode(FieldNode("age"), ComparisonOperator.GE, LiteralNode(18)),
                ComparisonNode(FieldNode("status"), ComparisonOperator.EQ, LiteralNode("active")),
            ),
            ComparisonNode(FieldNode("user.role"), ComparisonOperator.EQ, LiteralNode("admin")),
        )

        ast = WhereClauseAST(ast_root)
        result = ast.evaluate(sample_data)
        assert result is True


class TestFieldExistsHelper:
    """Test _field_exists helper that distinguishes None value from missing field."""

    def test_existing_field_returns_true(self):
        assert _field_exists({"name": "John"}, "name") is True

    def test_missing_field_returns_false(self):
        assert _field_exists({"name": "John"}, "age") is False

    def test_none_value_returns_true(self):
        """A field that exists but has value None should return True."""
        assert _field_exists({"balance": None}, "balance") is True

    def test_nested_field_exists(self):
        assert _field_exists({"user": {"id": 1}}, "user.id") is True

    def test_nested_field_missing(self):
        assert _field_exists({"user": {"id": 1}}, "user.role") is False

    def test_non_dict_data_returns_false(self):
        assert _field_exists("not a dict", "field") is False


class TestMissingFieldError:
    """Test that evaluate_node raises ValueError on missing fields."""

    def test_missing_field_raises_with_available_fields(self):
        """Accessing a missing field raises ValueError listing available fields."""
        data = {"name": "John", "age": 25}

        with pytest.raises(ValueError, match="does not exist") as exc_info:
            evaluate_node(FieldNode("nonexistent_xyz"), data)

        error_msg = str(exc_info.value)
        assert "nonexistent_xyz" in error_msg
        assert "age" in error_msg
        assert "name" in error_msg

    def test_missing_field_raises_every_call(self):
        """Each call with a missing field raises independently (no dedup)."""
        data = {"name": "John"}

        for _ in range(3):
            with pytest.raises(ValueError, match="does not exist"):
                evaluate_node(FieldNode("missing_field"), data)

    def test_existing_none_field_no_error(self):
        """A field that exists with None value should NOT raise."""
        data = {"balance": None}
        result = evaluate_node(FieldNode("balance"), data)
        assert result is None

    def test_missing_field_is_null_returns_true(self):
        """IS_NULL on a missing field returns True (missing is conceptually null)."""
        data = {"name": "John"}
        node = ComparisonNode(FieldNode("missing"), ComparisonOperator.IS_NULL)
        assert evaluate_node(node, data) is True

    def test_missing_field_is_not_null_returns_false(self):
        """IS_NOT_NULL on a missing field returns False."""
        data = {"name": "John"}
        node = ComparisonNode(FieldNode("missing"), ComparisonOperator.IS_NOT_NULL)
        assert evaluate_node(node, data) is False

    def test_is_null_with_function_error_does_not_swallow(self):
        """IS_NULL should not swallow non-missing-field ValueErrors."""
        data = {"name": "John"}
        # A function that raises a non-missing-field ValueError
        bad_func = FunctionNode("UNKNOWN_FUNC", [LiteralNode("x")])
        node = ComparisonNode(bad_func, ComparisonOperator.IS_NULL)
        with pytest.raises(ValueError, match="not registered"):
            evaluate_node(node, data)

    def test_custom_function_overrides_builtin(self):
        """Custom function overriding a built-in name should receive *args, not list."""
        data = {"name": "hello"}

        # Override LENGTH with a custom function that expects *args
        def custom_length(val):
            return len(str(val)) * 10  # distinguishable from built-in

        node = FunctionNode("LENGTH", [FieldNode("name")])
        result = evaluate_node(node, data, functions={"LENGTH": custom_length})
        assert result == 50  # len("hello") * 10


class TestParserBooleanLiterals:
    """Regression tests for GitHub issue #1221 — lowercase boolean literals in guard conditions.

    Before the fix, 'true'/'false' were parsed as FieldNode (field references) rather than
    LiteralNode because 'field_name' appeared before 'boolean' in the operand alternation.
    This caused a MissingFieldError at runtime ('true' not found in data) and a silent G002.
    """

    @pytest.fixture
    def parser(self):
        return WhereClauseParser()

    @pytest.mark.parametrize(
        "literal,expected_bool",
        [
            ("true", True), ("True", True), ("TRUE", True),
            ("false", False), ("False", False), ("FALSE", False),
        ],
    )
    def test_boolean_literals_parse_correctly(self, parser, literal, expected_bool):
        """Boolean literals in any case must parse as LiteralNode, not FieldNode."""
        result = parser.parse(f"passes_filter == {literal}")
        assert result.success, f"Expected successful parse, got: {result.error}"
        assert result.ast.evaluate({"passes_filter": expected_bool}) is True
        assert result.ast.evaluate({"passes_filter": not expected_bool}) is False

    def test_lowercase_true_does_not_raise_missing_field_error(self, parser):
        """Evaluating 'field == true' must NOT raise MissingFieldError for 'true'."""
        result = parser.parse("passes_filter == true")
        assert result.success
        assert result.ast.evaluate({"passes_filter": True}) is True  # correct value, not just no-raise

    @pytest.mark.parametrize("keyword", ["null", "and", "or", "not", "in", "is", "like", "between", "contains"])
    def test_reserved_words_do_not_parse_as_field_names(self, parser, keyword):
        """Reserved SQL keywords must not be accepted as field names regardless of case."""
        # A condition using the keyword as a bare operand should not yield a FieldNode.
        # We verify indirectly: the parse either succeeds (keyword is a valid literal/op)
        # or fails (invalid syntax) — but must NOT succeed and then raise MissingFieldError
        # when evaluated against data that lacks a field named after the keyword.
        result = parser.parse(f"score > 0 AND {keyword.upper()} IS NULL")
        # The important invariant: no MissingFieldError for the keyword token itself.
        if result.success:
            try:
                result.ast.evaluate({"score": 5})
            except MissingFieldError as e:
                pytest.fail(f"Reserved word '{keyword}' was treated as a field reference: {e}")

    @pytest.mark.parametrize("field", ["true_count", "nothing", "is_active", "not_valid", "inner", "android"])
    def test_reserved_word_prefix_fields_still_parse(self, parser, field):
        """Field names that begin with or contain reserved words must still be valid identifiers."""
        result = parser.parse(f"{field} == 1")
        assert result.success, f"Field name '{field}' should parse successfully, got: {result.error}"
        assert result.ast.evaluate({field: 1}) is True
        assert result.ast.evaluate({field: 2}) is False
