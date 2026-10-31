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
from agent_actions.input.preprocessing.parsing.parser import WhereClauseParser

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

    def test_raised_for_an_unregistered_function(self):
        """An unregistered name is a structural problem, not a data problem: every
        record would fail the same way, so a plain ValueError (which respects
        passthrough_on_error and would silently disable the guard) is wrong here."""
        with pytest.raises(GuardSemanticError, match="not registered"):
            WhereClauseParser().parse("COUNT(x) > 0").ast.evaluate({"x": "1"})

    def test_raised_for_the_wrong_argument_count(self):
        with pytest.raises(GuardSemanticError, match="exactly 1 argument"):
            WhereClauseParser().parse("TRIM(x, y) > 0").ast.evaluate({"x": "1", "y": "2"})

    def test_a_correct_function_call_still_evaluates_normally(self):
        assert WhereClauseParser().parse("LENGTH(x) > 1").ast.evaluate({"x": "ab"}) is True


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

    def test_an_unregistered_function_call_is_classified_semantic_not_data(self):
        """Through the real GuardFilter path, not a hand-built FilterResult: a DATA
        classification here would respect passthrough_on_error and silently pass
        every record through a guard that was supposed to filter them."""
        gf = GuardFilter()
        result = gf.filter_item(FilterItemRequest(data={"x": "1"}, condition="COUNT(x) > 0"))
        assert result.success is False
        assert result.error_category == ErrorCategory.SEMANTIC
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
    @pytest.mark.parametrize(
        ("behavior", "should_execute"),
        [
            pytest.param("filter", False, id="filter"),
            pytest.param("skip", False, id="skip"),
            # warn executes but flags the record
            pytest.param("warn", True, id="warn"),
        ],
    )
    def test_semantic_error_applies_on_false_despite_passthrough(self, behavior, should_execute):
        result = FilterResult(
            success=False, error="unquoted string", error_category=ErrorCategory.SEMANTIC
        )
        guard_result = GuardResult.from_filter_result(
            result, behavior=behavior, passthrough_on_error=True
        )
        assert guard_result.should_execute is should_execute
        assert guard_result.behavior == behavior

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
