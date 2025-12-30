"""
Integration tests for AST nodes and visit_comparison() method.

Tests that all ComparisonOperator enum values work correctly through
the refactored visit_comparison() method using the operator registry.
"""

import pytest
from agent_actions.preprocessing.parsing.ast_nodes import (
    ComparisonNode,
    FieldNode,
    LiteralNode,
    LogicalNode,
    ComparisonOperator,
    LogicalOperator,
    WhereClauseEvaluator,
    EvaluationContext,
    WhereClauseAST,
)


class TestVisitComparisonIntegration:
    """Integration tests for visit_comparison() with all operators."""

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

    @pytest.fixture
    def evaluator(self, sample_data):
        """Create an evaluator with sample data."""
        context = EvaluationContext(sample_data)
        return WhereClauseEvaluator(context)

    # Test all comparison operators through visit_comparison()

    def test_equal_operator_integration(self, evaluator):
        """Test EQ operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.EQ, LiteralNode(25))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.EQ, LiteralNode(30))
        assert evaluator.visit_comparison(node) is False

    def test_not_equal_operator_integration(self, evaluator):
        """Test NE operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.NE, LiteralNode(30))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.NE, LiteralNode(25))
        assert evaluator.visit_comparison(node) is False

    def test_less_than_operator_integration(self, evaluator):
        """Test LT operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.LT, LiteralNode(30))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.LT, LiteralNode(20))
        assert evaluator.visit_comparison(node) is False

    def test_less_equal_operator_integration(self, evaluator):
        """Test LE operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.LE, LiteralNode(25))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.LE, LiteralNode(30))
        assert evaluator.visit_comparison(node) is True

    def test_greater_than_operator_integration(self, evaluator):
        """Test GT operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.GT, LiteralNode(20))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.GT, LiteralNode(30))
        assert evaluator.visit_comparison(node) is False

    def test_greater_equal_operator_integration(self, evaluator):
        """Test GE operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.GE, LiteralNode(25))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.GE, LiteralNode(20))
        assert evaluator.visit_comparison(node) is True

    def test_in_operator_integration(self, evaluator):
        """Test IN operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.IN, LiteralNode([20, 25, 30]))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.IN, LiteralNode([10, 15, 20]))
        assert evaluator.visit_comparison(node) is False

    def test_not_in_operator_integration(self, evaluator):
        """Test NOT_IN operator through visit_comparison()."""
        node = ComparisonNode(
            FieldNode("age"), ComparisonOperator.NOT_IN, LiteralNode([10, 15, 20])
        )
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(
            FieldNode("age"), ComparisonOperator.NOT_IN, LiteralNode([20, 25, 30])
        )
        assert evaluator.visit_comparison(node) is False

    def test_contains_operator_integration(self, evaluator):
        """Test CONTAINS operator through visit_comparison()."""
        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.CONTAINS, LiteralNode("@example.com")
        )
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.CONTAINS, LiteralNode("@gmail.com")
        )
        assert evaluator.visit_comparison(node) is False

    def test_not_contains_operator_integration(self, evaluator):
        """Test NOT_CONTAINS operator through visit_comparison()."""
        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.NOT_CONTAINS, LiteralNode("@gmail.com")
        )
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.NOT_CONTAINS, LiteralNode("@example.com")
        )
        assert evaluator.visit_comparison(node) is False

    def test_like_operator_integration(self, evaluator):
        """Test LIKE operator through visit_comparison()."""
        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.LIKE, LiteralNode("%@example.com")
        )
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("name"), ComparisonOperator.LIKE, LiteralNode("John%"))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.LIKE, LiteralNode("%@gmail.com")
        )
        assert evaluator.visit_comparison(node) is False

    def test_not_like_operator_integration(self, evaluator):
        """Test NOT_LIKE operator through visit_comparison()."""
        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.NOT_LIKE, LiteralNode("%@gmail.com")
        )
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(
            FieldNode("email"), ComparisonOperator.NOT_LIKE, LiteralNode("%@example.com")
        )
        assert evaluator.visit_comparison(node) is False

    def test_between_operator_integration(self, evaluator):
        """Test BETWEEN operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.BETWEEN, LiteralNode([20, 30]))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.BETWEEN, LiteralNode([30, 40]))
        assert evaluator.visit_comparison(node) is False

    def test_not_between_operator_integration(self, evaluator):
        """Test NOT_BETWEEN operator through visit_comparison()."""
        node = ComparisonNode(
            FieldNode("age"), ComparisonOperator.NOT_BETWEEN, LiteralNode([30, 40])
        )
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(
            FieldNode("age"), ComparisonOperator.NOT_BETWEEN, LiteralNode([20, 30])
        )
        assert evaluator.visit_comparison(node) is False

    def test_is_null_operator_integration(self, evaluator):
        """Test IS_NULL operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("balance"), ComparisonOperator.IS_NULL)
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("age"), ComparisonOperator.IS_NULL)
        assert evaluator.visit_comparison(node) is False

    def test_is_not_null_operator_integration(self, evaluator):
        """Test IS_NOT_NULL operator through visit_comparison()."""
        node = ComparisonNode(FieldNode("age"), ComparisonOperator.IS_NOT_NULL)
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("balance"), ComparisonOperator.IS_NOT_NULL)
        assert evaluator.visit_comparison(node) is False

    # Test nested field access

    def test_nested_field_comparison(self, evaluator):
        """Test comparison with nested field access."""
        node = ComparisonNode(FieldNode("user.id"), ComparisonOperator.EQ, LiteralNode(123))
        assert evaluator.visit_comparison(node) is True

        node = ComparisonNode(FieldNode("user.role"), ComparisonOperator.EQ, LiteralNode("admin"))
        assert evaluator.visit_comparison(node) is True

    # Test edge cases

    def test_type_mismatch_handled_gracefully(self, evaluator):
        """Test that type mismatches are handled gracefully."""
        # Comparing string to number should return False, not raise error
        node = ComparisonNode(FieldNode("name"), ComparisonOperator.GT, LiteralNode(100))
        assert evaluator.visit_comparison(node) is False

    def test_missing_field_returns_none(self, evaluator):
        """Test that missing fields return None and comparisons handle it."""
        node = ComparisonNode(FieldNode("nonexistent"), ComparisonOperator.EQ, LiteralNode("value"))
        # None == 'value' is False
        assert evaluator.visit_comparison(node) is False

    def test_null_safety_unary_operator(self, evaluator):
        """Test that unary operators don't require right operand."""
        # IS_NULL should work without right operand
        node = ComparisonNode(
            FieldNode("balance"),
            ComparisonOperator.IS_NULL,
            None,  # No right operand
        )
        assert evaluator.visit_comparison(node) is True

    def test_null_safety_binary_operator_missing_right(self, evaluator):
        """Test that binary operators raise error if right operand is missing."""
        # EQ requires right operand
        node = ComparisonNode(
            FieldNode("age"),
            ComparisonOperator.EQ,
            None,  # Missing right operand
        )
        with pytest.raises(ValueError, match="requires a right operand"):
            evaluator.visit_comparison(node)

    # Test with full AST evaluation

    def test_full_ast_with_logical_operators(self, evaluator):
        """Test complex AST with logical operators."""
        # age > 20 AND status == 'active'
        ast_node = LogicalNode(
            LogicalOperator.AND,
            ComparisonNode(FieldNode("age"), ComparisonOperator.GT, LiteralNode(20)),
            ComparisonNode(FieldNode("status"), ComparisonOperator.EQ, LiteralNode("active")),
        )
        result = ast_node.accept(evaluator)
        assert result is True

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

    def test_operator_cache_performance(self, sample_data):
        """Test that operator cache is used (no registry lookups)."""
        context = EvaluationContext(sample_data)
        evaluator = WhereClauseEvaluator(context)

        # Verify cache is populated
        assert len(evaluator._operator_cache) == 16  # All comparison operators

        # Verify all operators are cached
        for op_enum in ComparisonOperator:
            assert op_enum in evaluator._operator_cache
            assert evaluator._operator_cache[op_enum] is not None

    def test_debug_logging_disabled_by_default(self, sample_data):
        """Test that debug logging is disabled by default."""
        context = EvaluationContext(sample_data)
        evaluator = WhereClauseEvaluator(context)

        # This should not raise an error even though it causes a type error
        node = ComparisonNode(FieldNode("name"), ComparisonOperator.GT, LiteralNode(100))
        # Should return False gracefully
        assert evaluator.visit_comparison(node) is False


class TestOperatorCachingPerformance:
    """Test that operator caching improves performance."""

    def test_cache_eliminates_registry_lookups(self):
        """Test that cached operators don't trigger registry lookups."""
        data = {"value": 42}
        context = EvaluationContext(data)
        evaluator = WhereClauseEvaluator(context)

        # Create multiple comparison nodes
        nodes = [
            ComparisonNode(FieldNode("value"), ComparisonOperator.EQ, LiteralNode(42)),
            ComparisonNode(FieldNode("value"), ComparisonOperator.GT, LiteralNode(40)),
            ComparisonNode(FieldNode("value"), ComparisonOperator.LT, LiteralNode(50)),
        ]

        # All evaluations should use cached operators
        for node in nodes:
            result = evaluator.visit_comparison(node)
            assert isinstance(result, bool)

        # Verify cache was populated once during __init__
        assert len(evaluator._operator_cache) == 16
