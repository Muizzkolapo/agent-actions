"""Tests for ValidationStrategy with malformed configuration.

Verifies that malformed strategy configs (non-callable validation_func,
invalid on_exhausted, negative max_attempts) are handled gracefully —
either at init or at evaluate() time — without producing KeyError or
other unhelpful tracebacks.
"""

from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.evaluation.strategies.validation import (
    ValidationStrategy,
)


def _make_batch_result(
    success: bool = True, content: dict | None = None, custom_id: str = "test_id"
) -> BatchResult:
    """Create a BatchResult for testing."""
    result = BatchResult(
        custom_id=custom_id,
        content=content or {"answer": "hello"},
        success=success,
    )
    return result


class TestSkipStrategyMalformedConfig:
    """Tests for ValidationStrategy with invalid/malformed configurations."""

    def test_none_validation_func_evaluate_returns_failed(self):
        """None as validation_func → evaluate returns FAILED (not TypeError)."""
        # safe_validate catches Exception when called with catch=(Exception,)
        strategy = ValidationStrategy(
            validation_func=None,  # type: ignore[arg-type]
            feedback_message="fix it",
        )

        result = _make_batch_result(success=True)
        outcome = strategy.evaluate(result)

        # safe_validate should catch the TypeError from calling None
        assert outcome.passed is False
        assert outcome.failure_type == "udf_fail"

    def test_non_callable_validation_func_evaluate_returns_failed(self):
        """String as validation_func → evaluate returns FAILED gracefully."""
        strategy = ValidationStrategy(
            validation_func="not_a_function",  # type: ignore[arg-type]
            feedback_message="fix it",
        )

        result = _make_batch_result(success=True)
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "udf_fail"

    def test_negative_max_attempts_stored_without_error(self):
        """Negative max_attempts is accepted at init (validated downstream)."""
        strategy = ValidationStrategy(
            validation_func=lambda x: True,
            feedback_message="fix it",
            max_attempts=-1,
        )

        assert strategy.max_attempts == -1

    def test_invalid_on_exhausted_stored_without_error(self):
        """Invalid on_exhausted value is accepted at init."""
        strategy = ValidationStrategy(
            validation_func=lambda x: True,
            feedback_message="fix it",
            on_exhausted="crash_everything",
        )

        assert strategy.on_exhausted == "crash_everything"

    def test_validation_func_that_raises_returns_failed(self):
        """Validation func raising arbitrary Exception → FAILED outcome."""

        def bad_validator(content):
            raise KeyError("missing expected field")

        strategy = ValidationStrategy(
            validation_func=bad_validator,
            feedback_message="fix it",
        )

        result = _make_batch_result(success=True)
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "udf_fail"

    def test_api_error_result_returns_failed_with_api_error_type(self):
        """When result.success is False, returns api_error failure type."""
        strategy = ValidationStrategy(
            validation_func=lambda x: True,
            feedback_message="fix it",
        )

        result = _make_batch_result(success=False)
        result.error = "rate limit exceeded"
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "api_error"

    def test_parse_error_in_json_mode_returns_parse_error_type(self):
        """String content in json_mode triggers parse_error classification."""
        strategy = ValidationStrategy(
            validation_func=lambda x: True,
            feedback_message="fix it",
            json_mode=True,
        )

        # String content in json_mode = parse error
        result = BatchResult(
            custom_id="test_id",
            content="not valid json {{{",
            success=True,
        )
        outcome = strategy.evaluate(result)

        assert outcome.passed is False
        assert outcome.failure_type == "parse_error"
