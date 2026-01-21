"""Tests for batch constants module.

TDD: These tests are written BEFORE the implementation to define
the expected behavior of BatchStatus, FilterStatus, and ContextMetaKeys.
"""

import pytest


class TestBatchStatus:
    """Tests for BatchStatus enum."""

    def test_all_status_values_exist(self):
        """BatchStatus should have all expected status values."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        assert hasattr(BatchStatus, "SUBMITTED")
        assert hasattr(BatchStatus, "VALIDATING")
        assert hasattr(BatchStatus, "IN_PROGRESS")
        assert hasattr(BatchStatus, "FINALIZING")
        assert hasattr(BatchStatus, "COMPLETED")
        assert hasattr(BatchStatus, "FAILED")
        assert hasattr(BatchStatus, "CANCELLED")

    def test_status_values_are_strings(self):
        """BatchStatus values should be string-compatible."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        assert BatchStatus.COMPLETED == "completed"
        assert BatchStatus.FAILED == "failed"
        assert BatchStatus.SUBMITTED == "submitted"
        assert BatchStatus.IN_PROGRESS == "in_progress"

    def test_status_string_conversion(self):
        """BatchStatus should convert to string properly."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        assert str(BatchStatus.COMPLETED) == "completed"
        assert f"{BatchStatus.FAILED}" == "failed"

    def test_terminal_states_includes_completed(self):
        """terminal_states() should include COMPLETED."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        terminal = BatchStatus.terminal_states()
        assert BatchStatus.COMPLETED in terminal

    def test_terminal_states_includes_failed(self):
        """terminal_states() should include FAILED."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        terminal = BatchStatus.terminal_states()
        assert BatchStatus.FAILED in terminal

    def test_terminal_states_includes_cancelled(self):
        """terminal_states() should include CANCELLED."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        terminal = BatchStatus.terminal_states()
        assert BatchStatus.CANCELLED in terminal

    def test_terminal_states_excludes_in_progress(self):
        """terminal_states() should NOT include IN_PROGRESS."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        terminal = BatchStatus.terminal_states()
        assert BatchStatus.IN_PROGRESS not in terminal

    def test_in_flight_states_includes_submitted(self):
        """in_flight_states() should include SUBMITTED."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        in_flight = BatchStatus.in_flight_states()
        assert BatchStatus.SUBMITTED in in_flight

    def test_in_flight_states_includes_in_progress(self):
        """in_flight_states() should include IN_PROGRESS."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        in_flight = BatchStatus.in_flight_states()
        assert BatchStatus.IN_PROGRESS in in_flight

    def test_in_flight_and_terminal_are_disjoint(self):
        """in_flight_states() and terminal_states() should not overlap."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        terminal = BatchStatus.terminal_states()
        in_flight = BatchStatus.in_flight_states()
        assert terminal.isdisjoint(in_flight)

    def test_is_terminal_method(self):
        """is_terminal() should correctly identify terminal states."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        assert BatchStatus.COMPLETED.is_terminal() is True
        assert BatchStatus.FAILED.is_terminal() is True
        assert BatchStatus.CANCELLED.is_terminal() is True
        assert BatchStatus.IN_PROGRESS.is_terminal() is False
        assert BatchStatus.SUBMITTED.is_terminal() is False

    def test_is_in_flight_method(self):
        """is_in_flight() should correctly identify in-flight states."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        assert BatchStatus.SUBMITTED.is_in_flight() is True
        assert BatchStatus.IN_PROGRESS.is_in_flight() is True
        assert BatchStatus.VALIDATING.is_in_flight() is True
        assert BatchStatus.COMPLETED.is_in_flight() is False
        assert BatchStatus.FAILED.is_in_flight() is False


class TestFilterStatus:
    """Tests for FilterStatus enum."""

    def test_all_filter_status_values_exist(self):
        """FilterStatus should have all expected values."""
        from agent_actions.llm_invocation.batch.core.batch_constants import FilterStatus

        assert hasattr(FilterStatus, "INCLUDED")
        assert hasattr(FilterStatus, "SKIPPED")
        assert hasattr(FilterStatus, "FILTERED")

    def test_filter_status_values_are_strings(self):
        """FilterStatus values should be string-compatible."""
        from agent_actions.llm_invocation.batch.core.batch_constants import FilterStatus

        assert FilterStatus.INCLUDED == "included"
        assert FilterStatus.SKIPPED == "skipped"
        assert FilterStatus.FILTERED == "filtered"

    def test_filter_status_string_conversion(self):
        """FilterStatus should convert to string properly."""
        from agent_actions.llm_invocation.batch.core.batch_constants import FilterStatus

        assert str(FilterStatus.INCLUDED) == "included"
        assert f"{FilterStatus.SKIPPED}" == "skipped"


class TestContextMetaKeys:
    """Tests for ContextMetaKeys constants."""

    def test_filter_status_key(self):
        """FILTER_STATUS should be the internal metadata key."""
        from agent_actions.llm_invocation.batch.core.batch_constants import ContextMetaKeys

        assert ContextMetaKeys.FILTER_STATUS == "_batch_filter_status"

    def test_passthrough_fields_key(self):
        """PASSTHROUGH_FIELDS should be the internal metadata key."""
        from agent_actions.llm_invocation.batch.core.batch_constants import ContextMetaKeys

        assert ContextMetaKeys.PASSTHROUGH_FIELDS == "_passthrough_fields"

    def test_all_keys_are_internal(self):
        """All meta keys should start with underscore (internal convention)."""
        from agent_actions.llm_invocation.batch.core.batch_constants import ContextMetaKeys

        assert ContextMetaKeys.FILTER_STATUS.startswith("_")
        assert ContextMetaKeys.PASSTHROUGH_FIELDS.startswith("_")

    def test_all_internal_keys_method(self):
        """all_internal_keys() should return set of all internal keys."""
        from agent_actions.llm_invocation.batch.core.batch_constants import ContextMetaKeys

        keys = ContextMetaKeys.all_internal_keys()
        assert isinstance(keys, set)
        assert "_batch_filter_status" in keys
        assert "_passthrough_fields" in keys


class TestEnumComparison:
    """Tests for enum comparison with string values."""

    def test_batch_status_equals_string(self):
        """BatchStatus should compare equal to its string value."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        assert BatchStatus.COMPLETED == "completed"
        assert "completed" == BatchStatus.COMPLETED

    def test_filter_status_equals_string(self):
        """FilterStatus should compare equal to its string value."""
        from agent_actions.llm_invocation.batch.core.batch_constants import FilterStatus

        assert FilterStatus.INCLUDED == "included"
        assert "included" == FilterStatus.INCLUDED

    def test_batch_status_in_list(self):
        """BatchStatus should work in list membership checks."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        statuses = ["submitted", "in_progress", "completed"]
        assert BatchStatus.COMPLETED in statuses
        assert BatchStatus.FAILED not in statuses

    def test_batch_status_as_dict_key(self):
        """BatchStatus should work as dictionary key."""
        from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

        status_map = {
            BatchStatus.COMPLETED: "done",
            BatchStatus.FAILED: "error",
        }
        # Should also be accessible via string
        assert status_map.get(BatchStatus.COMPLETED) == "done"
