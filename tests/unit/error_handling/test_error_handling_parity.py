"""
Test error handling parity between batch and online modes.

Tests for error handling divergences fixed in GitHub Issue #800:
- Guard exception handling (4 exception types)
- Error logging levels (WARNING for guards, ERROR for system failures)
- Null check protection for context_map

These tests include both verification tests and behavioral tests.
"""

import pytest
from unittest.mock import patch, MagicMock

from agent_actions.input.preprocessing.filtering.service import FilterService


class TestGuardExceptionHandling:
    """Verify guard exception handling catches all 4 exception types."""

    def test_guard_exception_tuple_includes_all_types(self):
        """Verify guard catches all 4 exception types."""
        import inspect

        source = inspect.getsource(FilterService._evaluate_guard)
        assert "(ValueError, TypeError, KeyError, AttributeError)" in source, (
            "Guard should catch all 4 exception types"
        )

    def test_conditional_clause_exception_tuple_includes_all_types(self):
        """Verify conditional clause catches all 4 exception types."""
        import inspect

        source = inspect.getsource(FilterService._evaluate_conditional_clause)
        assert "(ValueError, TypeError, KeyError, AttributeError)" in source, (
            "Conditional clause should catch all 4 exception types"
        )


class TestGuardLoggingLevelParity:
    """Verify guard logging levels are consistent between batch and online modes."""

    def test_batch_guard_uses_warning_level(self):
        """Verify batch guard uses WARNING level (not ERROR or DEBUG)."""
        import inspect

        source = inspect.getsource(FilterService._evaluate_guard)
        # Find the exception handler and verify it uses warning
        assert "logger.warning" in source, "Batch guard should use WARNING level for exceptions"
        # Should NOT use error for guard exceptions
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "except (" in line and "ValueError" in line:
                # Check the next few lines for the logger call
                for j in range(i, min(i + 5, len(lines))):
                    if "logger.error" in lines[j] and "guard" in lines[j].lower():
                        pytest.fail("Guard exceptions should use WARNING, not ERROR")

    def test_online_guard_uses_warning_level(self):
        """Verify online guard uses WARNING level (parity with batch)."""
        from agent_actions.processing.helpers import _evaluate_guard
        import inspect

        source = inspect.getsource(_evaluate_guard)
        assert "logger.warning" in source, "Online guard should use WARNING level for exceptions"

    def test_batch_conditional_clause_uses_warning_level(self):
        """Verify batch conditional clause uses WARNING level."""
        import inspect

        source = inspect.getsource(FilterService._evaluate_conditional_clause)
        assert "logger.warning" in source, "Batch conditional clause should use WARNING level"

    def test_online_conditional_clause_uses_warning_level(self):
        """Verify online conditional clause uses WARNING level (parity)."""
        from agent_actions.processing.helpers import _evaluate_conditional_clause
        import inspect

        source = inspect.getsource(_evaluate_conditional_clause)
        assert "logger.warning" in source, "Online conditional clause should use WARNING level"


class TestGuardBehavior:
    """Behavioral tests that actually trigger exception handling."""

    @pytest.fixture
    def filter_service(self):
        return FilterService()

    def test_guard_handles_type_error_gracefully(self, filter_service):
        """Guard should handle TypeError without crashing."""
        guard_config = {
            "clause": "age > 18",
            "behavior": "filter",
            "passthrough_on_error": True,
        }

        with patch.object(filter_service, "guard_filter") as mock_filter:
            mock_filter.filter_item.side_effect = TypeError("Cannot compare str with int")

            result = filter_service._evaluate_guard(
                item_content={"age": "not_a_number"}, guard_config=guard_config
            )

            # Should passthrough on error (not crash)
            assert result.should_include is True

    def test_guard_handles_key_error_gracefully(self, filter_service):
        """Guard should handle KeyError without crashing."""
        guard_config = {
            "clause": "user.profile.email == 'test@example.com'",
            "behavior": "filter",
            "passthrough_on_error": True,
        }

        with patch.object(filter_service, "guard_filter") as mock_filter:
            mock_filter.filter_item.side_effect = KeyError("profile")

            result = filter_service._evaluate_guard(
                item_content={"user": {}},  # Missing profile
                guard_config=guard_config,
            )

            # Should passthrough on error (not crash)
            assert result.should_include is True

    def test_guard_handles_attribute_error_gracefully(self, filter_service):
        """Guard should handle AttributeError without crashing."""
        guard_config = {
            "clause": "obj.missing_method()",
            "behavior": "filter",
            "passthrough_on_error": True,
        }

        with patch.object(filter_service, "guard_filter") as mock_filter:
            mock_filter.filter_item.side_effect = AttributeError("missing_method")

            result = filter_service._evaluate_guard(item_content={}, guard_config=guard_config)

            # Should passthrough on error (not crash)
            assert result.should_include is True

    def test_guard_respects_passthrough_on_error_false(self, filter_service):
        """Guard should filter (not passthrough) when passthrough_on_error=False."""
        guard_config = {
            "clause": "invalid_field == 'test'",
            "behavior": "filter",
            "passthrough_on_error": False,
        }

        with patch.object(filter_service, "guard_filter") as mock_filter:
            mock_filter.filter_item.side_effect = TypeError("Error")

            result = filter_service._evaluate_guard(item_content={}, guard_config=guard_config)

            # Should filter out when passthrough_on_error=False
            assert result.should_include is False


class TestBatchErrorLogging:
    """Verify batch processing uses ERROR level for actual system failures."""

    def test_preparator_uses_error_level_for_task_failures(self):
        """Verify BatchTaskPreparator logs task failures at ERROR level."""
        from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
        import inspect

        source = inspect.getsource(BatchTaskPreparator.prepare_tasks)

        # Task preparation failures ARE system errors (template errors, etc.)
        # Note: logger.exception() logs at ERROR level with traceback
        assert "logger.exception" in source and "Failed to prepare task" in source, (
            "Preparator should log task failures at ERROR level (using logger.exception)"
        )

    def test_result_processor_uses_error_level_for_processing_failures(self):
        """Verify BatchResultProcessor logs processing failures at ERROR level."""
        from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
        import inspect

        source = inspect.getsource(BatchResultProcessor._stage_3_4_process_results)

        # Processing failures ARE system errors
        assert "logger.error" in source, (
            "Result processor should log processing failures at ERROR level"
        )


class TestContextMapNullCheck:
    """Verify context_map access has null checks."""

    def test_result_processor_checks_custom_id_existence(self):
        """Verify result processor checks if custom_id exists in context_map."""
        from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
        import inspect

        source = inspect.getsource(BatchResultProcessor._process_successful_result)

        assert "custom_id in ctx.context_map" in source, (
            "Result processor should check if custom_id exists in context_map"
        )

    def test_result_processor_warns_on_missing_custom_id(self):
        """Verify result processor logs warning when custom_id is missing."""
        from agent_actions.llm.batch.processing.result_processor import BatchResultProcessor
        import inspect

        source = inspect.getsource(BatchResultProcessor._process_successful_result)

        assert "logger.warning" in source and "not found in context_map" in source, (
            "Result processor should warn when custom_id is missing from context_map"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
