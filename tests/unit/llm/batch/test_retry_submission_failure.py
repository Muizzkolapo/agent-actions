"""Tests for submit_retry_batch when the submission itself fails.

Two outcomes, and the caller has to tell them apart. A provider that throws is
transient: the function swallows it and answers None, because the next pass can
send the same records again. Records that cannot be rebuilt into a batch at all
raise RetrySubmissionImpossible, because no later pass changes that and the
caller must stop treating them as retryable.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError, mark_action_fatal
from agent_actions.llm.batch.services.retry_ops import (
    RetrySubmissionImpossible,
    resubmit_missing_records,
    submit_retry_batch,
)


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
                action_indices={},
                dependency_configs={},
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
                action_indices={},
                dependency_configs={},
            )

        assert result is None

    def test_an_action_fatal_prepare_error_propagates_instead_of_returning_none(
        self, mock_provider, context_map
    ):
        """A write-to-input refusal must fail the retry round, not be treated as
        transient — a later pass would hit the identical write again (1314)."""
        mock_cls = MagicMock()
        mock_cls.return_value.prepare_tasks.side_effect = mark_action_fatal(
            ConfigurationError("guard UDF wrote to its input")
        )

        with (
            patch(
                "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
                mock_cls,
            ),
            pytest.raises(ConfigurationError),
        ):
            submit_retry_batch(
                storage_backend=MagicMock(),
                provider=mock_provider,
                missing_ids={"rec_1"},
                context_map=context_map,
                output_directory="/tmp/output",
                file_name="batch_005",
                agent_config=None,
                action_indices={},
                dependency_configs={},
            )

    def test_no_matching_records_is_permanent_not_transient(self, mock_provider):
        """Ids absent from the context map cannot be rebuilt on any later pass."""
        context_map = {"other_id": {"target_id": "other_id"}}

        with pytest.raises(RetrySubmissionImpossible, match="context_map"):
            submit_retry_batch(
                storage_backend=MagicMock(),
                provider=mock_provider,
                missing_ids={"nonexistent_1", "nonexistent_2"},
                context_map=context_map,
                output_directory="/tmp/output",
                file_name="batch_003",
                agent_config=None,
                action_indices={},
                dependency_configs={},
            )

    def test_empty_prepared_tasks_is_permanent_not_transient(self, mock_provider, context_map):
        """Preparation admitting nothing will admit nothing next pass either."""
        with (
            patch(
                "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
                _mock_preparator([]),
            ),
            pytest.raises(RetrySubmissionImpossible, match="no tasks"),
        ):
            submit_retry_batch(
                storage_backend=MagicMock(),
                provider=mock_provider,
                missing_ids={"rec_1"},
                context_map=context_map,
                output_directory="/tmp/output",
                file_name="batch_004",
                agent_config=None,
                action_indices={},
                dependency_configs={},
            )
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
                action_indices={},
                dependency_configs={},
            )

        assert result == ("retry_batch_999", 2)


class TestResubmitMissingRecordsFailure:
    """resubmit_missing_records has the same transient-vs-fatal split (1314)."""

    def test_prepare_tasks_exception_returns_empty_list(self, mock_provider, context_map):
        """An ordinary exception is transient: the next pass can try again."""
        mock_cls = MagicMock()
        mock_cls.return_value.prepare_tasks.side_effect = ValueError("Invalid config")

        with patch(
            "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
            mock_cls,
        ):
            result = resubmit_missing_records(
                storage_backend=MagicMock(),
                provider=mock_provider,
                missing_ids={"rec_1"},
                context_map=context_map,
                output_directory="/tmp/output",
                file_name="batch_006",
                agent_config=None,
                action_indices={},
                dependency_configs={},
            )

        assert result == []

    def test_an_action_fatal_prepare_error_propagates_instead_of_returning_empty(
        self, mock_provider, context_map
    ):
        """A write-to-input refusal must fail the retry round, not be silently
        dropped as though the records could simply be tried again (1314)."""
        mock_cls = MagicMock()
        mock_cls.return_value.prepare_tasks.side_effect = mark_action_fatal(
            ConfigurationError("guard UDF wrote to its input")
        )

        with (
            patch(
                "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator",
                mock_cls,
            ),
            pytest.raises(ConfigurationError),
        ):
            resubmit_missing_records(
                storage_backend=MagicMock(),
                provider=mock_provider,
                missing_ids={"rec_1"},
                context_map=context_map,
                output_directory="/tmp/output",
                file_name="batch_007",
                agent_config=None,
                action_indices={},
                dependency_configs={},
            )
