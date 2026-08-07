"""Tests for RecordState enum and lifecycle state categories."""

from agent_actions.record.state import (
    CASCADE_BLOCKING_STATES,
    PROCESSABLE_STATES,
    RESETTABLE_DOWNSTREAM_STATES,
    RecordState,
)


class TestPublicPackageContract:
    def test_record_state_importable_from_package(self):
        from agent_actions.record import RecordState as RS

        assert RS.ACTIVE == "active"


class TestRecordStateEnum:
    def test_is_str_enum(self):
        assert isinstance(RecordState.ACTIVE, str)
        assert RecordState.ACTIVE == "active"

    def test_all_members_have_unique_values(self):
        values = [s.value for s in RecordState]
        assert len(values) == len(set(values))

    def test_member_count(self):
        assert len(RecordState) == 6


class TestStateCategories:
    def test_only_active_is_processable(self):
        assert PROCESSABLE_STATES == {RecordState.ACTIVE}

    def test_resettable_does_not_overlap_blocking(self):
        assert RESETTABLE_DOWNSTREAM_STATES & CASCADE_BLOCKING_STATES == set()

    def test_resettable_plus_blocking_covers_all_non_processable(self):
        assert (
            RESETTABLE_DOWNSTREAM_STATES | CASCADE_BLOCKING_STATES
            == frozenset(RecordState) - PROCESSABLE_STATES
        )

    def test_guard_skipped_is_resettable(self):
        assert RecordState.GUARD_SKIPPED in RESETTABLE_DOWNSTREAM_STATES

    def test_cascade_skipped_blocks(self):
        assert RecordState.CASCADE_SKIPPED in CASCADE_BLOCKING_STATES

    def test_failed_blocks(self):
        assert RecordState.FAILED in CASCADE_BLOCKING_STATES

    def test_exhausted_blocks(self):
        assert RecordState.EXHAUSTED in CASCADE_BLOCKING_STATES
