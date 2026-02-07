"""Tests for batch constants module.

TDD: These tests are written BEFORE the implementation to define
the expected behavior of BatchStatus, FilterStatus, and ContextMetaKeys.
"""

import pytest


class TestBatchStatus:
    """Tests for BatchStatus enum."""

    def test_all_status_values_exist(self):
        """BatchStatus should have all expected status values."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        for name in (
            "SUBMITTED",
            "VALIDATING",
            "IN_PROGRESS",
            "FINALIZING",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
        ):
            assert hasattr(BatchStatus, name)

    @pytest.mark.parametrize(
        "member,expected",
        [
            ("COMPLETED", "completed"),
            ("FAILED", "failed"),
            ("SUBMITTED", "submitted"),
            ("IN_PROGRESS", "in_progress"),
        ],
        ids=["completed", "failed", "submitted", "in_progress"],
    )
    def test_status_values_are_strings(self, member, expected):
        """BatchStatus values should be string-compatible."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        assert getattr(BatchStatus, member) == expected

    def test_status_string_conversion(self):
        """BatchStatus should convert to string properly."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        assert str(BatchStatus.COMPLETED) == "completed"
        assert f"{BatchStatus.FAILED}" == "failed"

    @pytest.mark.parametrize(
        "member,in_terminal",
        [
            ("COMPLETED", True),
            ("FAILED", True),
            ("CANCELLED", True),
            ("IN_PROGRESS", False),
            ("SUBMITTED", False),
        ],
        ids=["completed", "failed", "cancelled", "in_progress", "submitted"],
    )
    def test_terminal_states_membership(self, member, in_terminal):
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        terminal = BatchStatus.terminal_states()
        status = getattr(BatchStatus, member)
        assert (status in terminal) is in_terminal

    @pytest.mark.parametrize(
        "member,in_flight",
        [
            ("SUBMITTED", True),
            ("IN_PROGRESS", True),
            ("VALIDATING", True),
            ("COMPLETED", False),
            ("FAILED", False),
        ],
        ids=["submitted", "in_progress", "validating", "completed", "failed"],
    )
    def test_in_flight_states_membership(self, member, in_flight):
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        in_flight_set = BatchStatus.in_flight_states()
        status = getattr(BatchStatus, member)
        assert (status in in_flight_set) is in_flight

    def test_in_flight_and_terminal_are_disjoint(self):
        """in_flight_states() and terminal_states() should not overlap."""
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        assert BatchStatus.terminal_states().isdisjoint(BatchStatus.in_flight_states())

    @pytest.mark.parametrize(
        "member,is_terminal",
        [
            ("COMPLETED", True),
            ("FAILED", True),
            ("CANCELLED", True),
            ("IN_PROGRESS", False),
            ("SUBMITTED", False),
        ],
    )
    def test_is_terminal_method(self, member, is_terminal):
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        assert getattr(BatchStatus, member).is_terminal() is is_terminal

    @pytest.mark.parametrize(
        "member,is_in_flight",
        [
            ("SUBMITTED", True),
            ("IN_PROGRESS", True),
            ("VALIDATING", True),
            ("COMPLETED", False),
            ("FAILED", False),
        ],
    )
    def test_is_in_flight_method(self, member, is_in_flight):
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        assert getattr(BatchStatus, member).is_in_flight() is is_in_flight


class TestFilterStatus:
    """Tests for FilterStatus enum."""

    def test_all_filter_status_values_exist(self):
        """FilterStatus should have all expected values."""
        from agent_actions.llm.batch.core.batch_constants import FilterStatus

        for name in ("INCLUDED", "SKIPPED", "FILTERED"):
            assert hasattr(FilterStatus, name)

    @pytest.mark.parametrize(
        "member,expected",
        [("INCLUDED", "included"), ("SKIPPED", "skipped"), ("FILTERED", "filtered")],
    )
    def test_filter_status_values_are_strings(self, member, expected):
        from agent_actions.llm.batch.core.batch_constants import FilterStatus

        assert getattr(FilterStatus, member) == expected

    def test_filter_status_string_conversion(self):
        from agent_actions.llm.batch.core.batch_constants import FilterStatus

        assert str(FilterStatus.INCLUDED) == "included"
        assert f"{FilterStatus.SKIPPED}" == "skipped"


class TestContextMetaKeys:
    """Tests for ContextMetaKeys constants."""

    @pytest.mark.parametrize(
        "attr,expected",
        [
            ("FILTER_STATUS", "_batch_filter_status"),
            ("PASSTHROUGH_FIELDS", "_passthrough_fields"),
        ],
    )
    def test_key_values(self, attr, expected):
        from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys

        value = getattr(ContextMetaKeys, attr)
        assert value == expected
        assert value.startswith("_")

    def test_all_internal_keys_method(self):
        """all_internal_keys() should return set of all internal keys."""
        from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys

        keys = ContextMetaKeys.all_internal_keys()
        assert isinstance(keys, set)
        assert "_batch_filter_status" in keys
        assert "_passthrough_fields" in keys


class TestEnumComparison:
    """Tests for enum comparison with string values."""

    def test_batch_status_equals_string(self):
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        assert BatchStatus.COMPLETED == "completed"
        assert "completed" == BatchStatus.COMPLETED

    def test_filter_status_equals_string(self):
        from agent_actions.llm.batch.core.batch_constants import FilterStatus

        assert FilterStatus.INCLUDED == "included"
        assert "included" == FilterStatus.INCLUDED

    def test_batch_status_in_list(self):
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        statuses = ["submitted", "in_progress", "completed"]
        assert BatchStatus.COMPLETED in statuses
        assert BatchStatus.FAILED not in statuses

    def test_batch_status_as_dict_key(self):
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        status_map = {
            BatchStatus.COMPLETED: "done",
            BatchStatus.FAILED: "error",
        }
        assert status_map.get(BatchStatus.COMPLETED) == "done"
