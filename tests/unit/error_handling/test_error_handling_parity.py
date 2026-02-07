"""
Test error handling parity between batch and online modes.

Behavioral tests for guard exception handling (GitHub Issue #800).
"""

import pytest
from unittest.mock import patch

from agent_actions.input.preprocessing.filtering.service import FilterService


class TestGuardBehavior:
    """Behavioral tests that actually trigger exception handling."""

    @pytest.fixture
    def filter_service(self):
        return FilterService()

    @pytest.mark.parametrize(
        "exception,passthrough_on_error,expected_include",
        [
            pytest.param(TypeError("Cannot compare"), True, True, id="type_error_passthrough"),
            pytest.param(KeyError("profile"), True, True, id="key_error_passthrough"),
            pytest.param(AttributeError("missing_method"), True, True, id="attr_error_passthrough"),
            pytest.param(TypeError("Error"), False, False, id="passthrough_false_filters"),
        ],
    )
    def test_guard_handles_exception(
        self, filter_service, exception, passthrough_on_error, expected_include
    ):
        guard_config = {
            "clause": "some_clause",
            "behavior": "filter",
            "passthrough_on_error": passthrough_on_error,
        }

        with patch.object(filter_service, "guard_filter") as mock_filter:
            mock_filter.filter_item.side_effect = exception

            result = filter_service._evaluate_guard(item_content={}, guard_config=guard_config)

            assert result.should_include is expected_include
