"""Tests for batch constants module."""


class TestBatchStatus:
    """Tests for BatchStatus enum."""

    def test_in_flight_and_terminal_are_disjoint(self):
        """in_flight_states() and terminal_states() should not overlap."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        assert BatchStatus.terminal_states().isdisjoint(BatchStatus.in_flight_states())
