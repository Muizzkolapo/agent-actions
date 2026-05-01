"""Tests for RecordState enum and lifecycle helpers."""

import pytest

from agent_actions.record.state import (
    CASCADE_BLOCKING_STATES,
    PROCESSABLE_STATES,
    RESETTABLE_DOWNSTREAM_STATES,
    RETRIABLE_STATES,
    SETTLED_STATES,
    RecordState,
    is_processable,
    is_retriable,
    is_settled,
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
        assert len(RecordState) == 8


class TestStateCategories:
    def test_only_active_is_processable(self):
        assert PROCESSABLE_STATES == {RecordState.ACTIVE}

    def test_active_is_not_settled(self):
        assert RecordState.ACTIVE not in SETTLED_STATES

    def test_every_non_active_state_is_settled(self):
        for state in RecordState:
            if state != RecordState.ACTIVE:
                assert state in SETTLED_STATES, f"{state} should be settled"

    def test_resettable_does_not_overlap_blocking(self):
        assert RESETTABLE_DOWNSTREAM_STATES & CASCADE_BLOCKING_STATES == set()

    def test_resettable_plus_blocking_covers_all_settled(self):
        assert RESETTABLE_DOWNSTREAM_STATES | CASCADE_BLOCKING_STATES == SETTLED_STATES

    def test_retriable_is_subset_of_blocking(self):
        assert RETRIABLE_STATES <= CASCADE_BLOCKING_STATES

    def test_guard_skipped_is_resettable(self):
        assert RecordState.GUARD_SKIPPED in RESETTABLE_DOWNSTREAM_STATES

    def test_cascade_skipped_blocks(self):
        assert RecordState.CASCADE_SKIPPED in CASCADE_BLOCKING_STATES

    def test_failed_blocks_and_is_retriable(self):
        assert RecordState.FAILED in CASCADE_BLOCKING_STATES
        assert RecordState.FAILED in RETRIABLE_STATES

    def test_exhausted_blocks_and_is_retriable(self):
        assert RecordState.EXHAUSTED in CASCADE_BLOCKING_STATES
        assert RecordState.EXHAUSTED in RETRIABLE_STATES


class TestHelperFunctions:
    @pytest.mark.parametrize("state", list(RecordState))
    def test_is_processable_matches_set(self, state):
        assert is_processable(state) == (state in PROCESSABLE_STATES)

    @pytest.mark.parametrize("state", list(RecordState))
    def test_is_settled_matches_set(self, state):
        assert is_settled(state) == (state in SETTLED_STATES)

    @pytest.mark.parametrize("state", list(RecordState))
    def test_is_retriable_matches_set(self, state):
        assert is_retriable(state) == (state in RETRIABLE_STATES)
