"""
Test error handling parity between batch and online modes.

Behavioral tests for guard exception handling (GitHub Issue #800).
"""

from unittest.mock import patch

import pytest

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator


class TestGuardBehavior:
    """Behavioral tests that actually trigger exception handling."""

    @pytest.fixture
    def evaluator(self):
        return GuardEvaluator()

    @pytest.mark.parametrize(
        "exception,passthrough_on_error,expected_execute",
        [
            pytest.param(TypeError("Cannot compare"), True, True, id="type_error_passthrough"),
            pytest.param(KeyError("profile"), True, True, id="key_error_passthrough"),
            pytest.param(AttributeError("missing_method"), True, True, id="attr_error_passthrough"),
            pytest.param(TypeError("Error"), False, False, id="passthrough_false_filters"),
        ],
    )
    def test_guard_handles_exception(
        self, evaluator, exception, passthrough_on_error, expected_execute
    ):
        guard_config = {
            "clause": "some_clause",
            "behavior": "filter",
            "passthrough_on_error": passthrough_on_error,
        }

        with patch.object(evaluator, "_filter") as mock_filter:
            mock_filter.filter_item.side_effect = exception

            result = evaluator._evaluate_guard(context={}, guard_config=guard_config)

            assert result.should_execute is expected_execute
