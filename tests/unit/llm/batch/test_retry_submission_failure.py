"""Tests for submit_retry_batch when the submission itself fails.

Verifies that when provider.submit_batch raises an exception,
the function catches it, logs a warning, and returns None —
rather than propagating the exception or leaving records dangling.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.services.retry_ops import submit_retry_batch


@pytest.fixture
def mock_provider():
    """Create a mock batch provider."""
    provider = MagicMock()
    provider.submit_batch.return_value = ("retry_batch_001", 3)
    return provider


@pytest.fixture
def context_map():
    """Context map with records keyed by custom_id."""
    return {
        "rec_1": {"target_id": "rec_1", "field": "value_1"},
        "rec_2": {"target_id": "rec_2", "field": "value_2"},
        "rec_3": {"target_id": "rec_3", "field": "value_3"},
    }


def _mock_preparator(tasks):
    """Create a mock BatchTaskPreparator class that returns given tasks."""
    mock_cls = MagicMock()
    mock_prepared = MagicMock()
    mock_prepared.tasks = tasks
    mock_cls.return_value.prepare_tasks.return_value = mock_prepared
    return mock_cls


class TestRetrySubmissionFailure:
    """Tests for submit_retry_batch error handling."""

    def test_submit_batch_exception_returns_none(self, mock_provider, context_map):
        """When provider.submit_batch raises, function returns None."""
        mock_provider.submit_batch.side_effect = RuntimeError("OpenAI API rate limit")

        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
            _mock_preparator([{"task": "data"}]),
        ):
            result = submit_retry_batch(
                storage_backend=MagicMock(),
                provider=mock_provider,
                missing_ids={"rec_1", "rec_2"},
                context_map=context_map,
                output_directory="/tmp/output",
                file_name="batch_001",
                agent_config={"model": "gpt-4"},
            )

        assert result is None

    def test_prepare_tasks_exception_returns_none(self, mock_provider, context_map):
        """When prepare_tasks raises, function catches and returns None."""
        mock_cls = MagicMock()
        mock_cls.return_value.prepare_tasks.side_effect = ValueError("Invalid config")

        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
            mock_cls,
        ):
            result = submit_retry_batch(
                storage_backend=MagicMock(),
                provider=mock_provider,
                missing_ids={"rec_1"},
                context_map=context_map,
                output_directory="/tmp/output",
                file_name="batch_002",
                agent_config=None,
            )

        assert result is None

    def test_no_matching_records_returns_none(self, mock_provider):
        """When missing_ids don't match context_map, returns None."""
        context_map = {"other_id": {"target_id": "other_id"}}

        result = submit_retry_batch(
            storage_backend=MagicMock(),
            provider=mock_provider,
            missing_ids={"nonexistent_1", "nonexistent_2"},
            context_map=context_map,
            output_directory="/tmp/output",
            file_name="batch_003",
            agent_config=None,
        )

        assert result is None

    def test_empty_prepared_tasks_returns_none(self, mock_provider, context_map):
        """When prepare_tasks returns empty task list, returns None."""
        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
            _mock_preparator([]),
        ):
            result = submit_retry_batch(
                storage_backend=MagicMock(),
                provider=mock_provider,
                missing_ids={"rec_1"},
                context_map=context_map,
                output_directory="/tmp/output",
                file_name="batch_004",
                agent_config=None,
            )

        assert result is None
        mock_provider.submit_batch.assert_not_called()

    def test_successful_submission_returns_tuple(self, mock_provider, context_map):
        """Happy path: successful submission returns (batch_id, count)."""
        mock_provider.submit_batch.return_value = ("retry_batch_999", 2)

        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
            _mock_preparator([{"task": "1"}, {"task": "2"}]),
        ):
            result = submit_retry_batch(
                storage_backend=MagicMock(),
                provider=mock_provider,
                missing_ids={"rec_1", "rec_2"},
                context_map=context_map,
                output_directory="/tmp/output",
                file_name="batch_005",
                agent_config={"model": "gpt-4"},
            )

        assert result == ("retry_batch_999", 2)
