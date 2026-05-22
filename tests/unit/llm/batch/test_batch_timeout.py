"""Tests for wait_for_batch_completion timeout path.

Verifies that when the batch API never returns a terminal status,
the function times out gracefully — logging a warning and returning
the final check_status result instead of raising an exception.
"""

from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.services.retry_polling import wait_for_batch_completion


class TestWaitForBatchCompletionTimeout:
    """Tests for the timeout path in wait_for_batch_completion."""

    @patch("agent_actions.llm.batch.services.retry_polling.time")
    def test_timeout_returns_final_status_without_exception(self, mock_time):
        """When timeout expires, function returns provider.check_status result."""
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.IN_PROGRESS

        # Simulate time progression: start=0, first while check=0, second check exceeds timeout
        mock_time.time.side_effect = [
            0,  # start_time
            0,  # first while check
            0,  # first current_time
            100,  # second while check — exceeds timeout of 2
        ]
        mock_time.sleep = MagicMock()  # don't actually sleep

        result = wait_for_batch_completion(
            provider=provider,
            batch_id="batch_123",
            timeout_seconds=2,
            poll_interval=1,
            total_items=0,
        )

        # Should return the final check_status result
        assert result == BatchStatus.IN_PROGRESS

    @patch("agent_actions.llm.batch.services.retry_polling.time")
    def test_timeout_path_does_not_raise(self, mock_time):
        """Timeout returns a status value, never raises TimeoutError."""
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.IN_PROGRESS

        mock_time.time.side_effect = [0, 0, 0, 100]
        mock_time.sleep = MagicMock()

        # Should NOT raise — returns the last check_status value
        result = wait_for_batch_completion(
            provider=provider,
            batch_id="batch_timeout_test",
            timeout_seconds=5,
            poll_interval=1,
            total_items=0,
        )

        assert result is not None
        # Final check_status is called after the loop exits
        assert provider.check_status.call_count >= 2  # loop + final

    @patch("agent_actions.llm.batch.services.retry_polling.time")
    def test_completed_before_timeout_returns_immediately(self, mock_time):
        """If batch completes within timeout, returns COMPLETED without timeout."""
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.COMPLETED

        mock_time.time.side_effect = [0, 0, 0]
        mock_time.sleep = MagicMock()

        result = wait_for_batch_completion(
            provider=provider,
            batch_id="batch_fast",
            timeout_seconds=3600,
            poll_interval=30,
        )

        assert result == BatchStatus.COMPLETED
        # Should not have called the final check_status after the loop
        # (it exits via early return on COMPLETED)
        assert provider.check_status.call_count == 1

    @patch("agent_actions.llm.batch.services.retry_polling.time")
    def test_failed_status_returns_before_timeout(self, mock_time):
        """FAILED status is terminal — returns immediately."""
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.FAILED

        mock_time.time.side_effect = [0, 0, 0]
        mock_time.sleep = MagicMock()

        result = wait_for_batch_completion(
            provider=provider,
            batch_id="batch_fail",
            timeout_seconds=3600,
            poll_interval=30,
        )

        assert result == BatchStatus.FAILED

    @patch("agent_actions.llm.batch.services.retry_polling.time")
    def test_cancelled_status_returns_before_timeout(self, mock_time):
        """CANCELLED status is terminal — returns immediately."""
        provider = MagicMock()
        provider.check_status.return_value = BatchStatus.CANCELLED

        mock_time.time.side_effect = [0, 0, 0]
        mock_time.sleep = MagicMock()

        result = wait_for_batch_completion(
            provider=provider,
            batch_id="batch_cancel",
            timeout_seconds=3600,
            poll_interval=30,
        )

        assert result == BatchStatus.CANCELLED
