"""Tests for wait_for_batch_completion timeout path.

Verifies that when the batch API never returns a terminal status,
the function times out gracefully — returning the final check_status
result instead of raising an exception.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.services.retry_polling import wait_for_batch_completion


class TestWaitForBatchCompletionTimeout:
    """Tests for the timeout path in wait_for_batch_completion."""

    @patch("agent_actions.llm.batch.services.retry_polling.time")
    def test_timeout_returns_final_status_without_exception(self, mock_time):
        """When timeout expires, returns IN_PROGRESS and makes a final check_status call."""
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.IN_PROGRESS

        mock_time.time.side_effect = [
            0,  # start_time
            0,  # first while check
            0,  # first current_time
            100,  # second while check — exceeds timeout
            100,  # elapsed calculation after loop
        ]
        mock_time.sleep = MagicMock()

        result = wait_for_batch_completion(
            provider=provider,
            batch_id="batch_123",
            timeout_seconds=2,
            poll_interval=1,
            total_items=0,
        )

        assert result == BatchStatus.IN_PROGRESS
        assert provider.check_status.call_count >= 2  # loop + final

    @pytest.mark.parametrize(
        "terminal_status",
        [BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.CANCELLED],
    )
    @patch("agent_actions.llm.batch.services.retry_polling.time")
    def test_terminal_status_returns_before_timeout(self, mock_time, terminal_status):
        """Terminal statuses (COMPLETED/FAILED/CANCELLED) return immediately."""
        provider = MagicMock()
        provider.check_status.return_value = terminal_status

        mock_time.time.side_effect = [0, 0, 0]
        mock_time.sleep = MagicMock()

        result = wait_for_batch_completion(
            provider=provider,
            batch_id="batch_terminal",
            timeout_seconds=3600,
            poll_interval=30,
        )

        assert result == terminal_status
        assert provider.check_status.call_count == 1
