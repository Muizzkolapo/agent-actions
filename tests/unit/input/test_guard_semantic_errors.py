"""Tests for runtime guard semantic error handling, circuit breaker, and error taxonomy."""

import pytest

from agent_actions.input.preprocessing.filtering.evaluator import GuardResult
from agent_actions.input.preprocessing.filtering.guard_filter import (
    ErrorCategory,
    FilterItemRequest,
    FilterResult,
    GuardFilter,
    reset_global_guard_filter,
)
from agent_actions.input.preprocessing.parsing.ast_nodes import (
    ComparisonNode,
    ComparisonOperator,
    FieldNode,
    GuardSemanticError,
    LiteralNode,
    MissingFieldError,
    evaluate_node,
)

# ---------------------------------------------------------------------------
# GuardSemanticError — raised for RHS bare identifier
# ---------------------------------------------------------------------------


class TestGuardSemanticError:
    def test_is_value_error_subclass(self):
        assert issubclass(GuardSemanticError, ValueError)

    def test_raised_for_bare_rhs_field(self):
        """'status == approved' where approved is not a field raises GuardSemanticError."""
        node = ComparisonNode(
            left=FieldNode("status"),
            operator=ComparisonOperator.EQ,
            right=FieldNode("approved"),
        )
        data = {"status": "approved"}
        with pytest.raises(GuardSemanticError, match="quote"):
            evaluate_node(node, data)

    def test_left_side_missing_still_raises_missing_field_error(self):
        """Missing field on LEFT side is MissingFieldError, not GuardSemanticError."""
        node = ComparisonNode(
            left=FieldNode("nonexistent"),
            operator=ComparisonOperator.EQ,
            right=LiteralNode("value"),
        )
        data = {"other": "data"}
        with pytest.raises(MissingFieldError):
            evaluate_node(node, data)

    def test_is_null_still_works_for_missing_left(self):
        """IS_NULL on missing left field returns True (existing behavior preserved)."""
        node = ComparisonNode(
            left=FieldNode("nonexistent"),
            operator=ComparisonOperator.IS_NULL,
        )
        data = {"other": "data"}
        assert evaluate_node(node, data) is True

    def test_quoted_rhs_works_normally(self):
        """'status == \"approved\"' (LiteralNode RHS) evaluates normally."""
        node = ComparisonNode(
            left=FieldNode("status"),
            operator=ComparisonOperator.EQ,
            right=LiteralNode("approved"),
        )
        data = {"status": "approved"}
        assert evaluate_node(node, data) is True

    def test_error_message_includes_fix_suggestion(self):
        """Error message includes the exact quoted syntax to use."""
        node = ComparisonNode(
            left=FieldNode("hitl_status"),
            operator=ComparisonOperator.EQ,
            right=FieldNode("approved"),
        )
        data = {"hitl_status": "approved"}
        with pytest.raises(GuardSemanticError) as exc_info:
            evaluate_node(node, data)
        msg = str(exc_info.value)
        assert 'hitl_status == "approved"' in msg


# ---------------------------------------------------------------------------
# ErrorCategory on FilterResult
# ---------------------------------------------------------------------------


class TestErrorCategory:
    def test_default_is_none(self):
        result = FilterResult(success=True, matched=True)
        assert result.error_category is None

    def test_semantic_category(self):
        result = FilterResult(success=False, error="test", error_category=ErrorCategory.SEMANTIC)
        assert result.error_category == ErrorCategory.SEMANTIC

    def test_data_category(self):
        result = FilterResult(success=False, error="test", error_category=ErrorCategory.DATA)
        assert result.error_category == ErrorCategory.DATA


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    @pytest.fixture(autouse=True)
    def _reset_filter(self):
        reset_global_guard_filter()
        yield
        reset_global_guard_filter()

    def test_second_eval_hits_cache(self):
        """After first semantic error, second call returns cached result without re-evaluation."""
        gf = GuardFilter()
        condition = "status == unquoted"
        data = {"status": "active"}

        result1 = gf.filter_item(FilterItemRequest(data=data, condition=condition))
        assert result1.error_category == ErrorCategory.SEMANTIC

        result2 = gf.filter_item(FilterItemRequest(data=data, condition=condition))
        assert result2.error_category == ErrorCategory.SEMANTIC
        assert result2.error == result1.error

        summary = gf.get_error_summary()
        assert summary[condition] == 2
        gf.shutdown()

    def test_logs_once_not_n_times(self):
        """Same semantic error condition logs WARNING once, not per-record."""
        from unittest.mock import patch

        gf = GuardFilter()
        condition = "field == bareword"
        data = {"field": "value"}

        with patch(
            "agent_actions.input.preprocessing.filtering.guard_filter.logger"
        ) as mock_logger:
            for _ in range(10):
                gf.filter_item(FilterItemRequest(data=data, condition=condition))

        # logger.warning should be called exactly once (first occurrence only)
        warning_calls = [c for c in mock_logger.warning.call_args_list if "bareword" in str(c)]
        assert len(warning_calls) == 1
        gf.shutdown()


# ---------------------------------------------------------------------------
# Passthrough bypass for SEMANTIC errors
# ---------------------------------------------------------------------------


class TestPassthroughBypass:
    def test_semantic_error_ignores_passthrough_on_error(self):
        """SEMANTIC errors apply on_false behavior even when passthrough_on_error=True."""
        result = FilterResult(
            success=False, error="unquoted string", error_category=ErrorCategory.SEMANTIC
        )
        guard_result = GuardResult.from_filter_result(
            result, behavior="filter", passthrough_on_error=True
        )
        assert guard_result.should_execute is False
        assert guard_result.behavior == "filter"

    def test_semantic_error_with_skip_behavior(self):
        """SEMANTIC + on_false=skip -> skipped, not passed through."""
        result = FilterResult(
            success=False, error="unquoted string", error_category=ErrorCategory.SEMANTIC
        )
        guard_result = GuardResult.from_filter_result(
            result, behavior="skip", passthrough_on_error=True
        )
        assert guard_result.should_execute is False
        assert guard_result.behavior == "skip"

    def test_semantic_error_with_warn_behavior(self):
        """SEMANTIC + on_false=warn -> warned (execute but flag)."""
        result = FilterResult(
            success=False, error="unquoted string", error_category=ErrorCategory.SEMANTIC
        )
        guard_result = GuardResult.from_filter_result(
            result, behavior="warn", passthrough_on_error=True
        )
        assert guard_result.should_execute is True
        assert guard_result.behavior == "warn"

    def test_data_error_still_respects_passthrough(self):
        """DATA errors with passthrough_on_error=True still pass through (existing behavior)."""
        result = FilterResult(
            success=False, error="field missing", error_category=ErrorCategory.DATA
        )
        guard_result = GuardResult.from_filter_result(
            result, behavior="filter", passthrough_on_error=True
        )
        assert guard_result.should_execute is True  # passed through

    def test_data_error_no_passthrough_applies_behavior(self):
        """DATA errors with passthrough_on_error=False apply on_false behavior."""
        result = FilterResult(
            success=False, error="field missing", error_category=ErrorCategory.DATA
        )
        guard_result = GuardResult.from_filter_result(
            result, behavior="filter", passthrough_on_error=False
        )
        assert guard_result.should_execute is False
        assert guard_result.behavior == "filter"
