"""Tests for RecordState enum and lifecycle state categories."""

import pytest

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

    @pytest.mark.parametrize(
        ("state", "category"),
        [
            pytest.param(
                RecordState.GUARD_SKIPPED,
                RESETTABLE_DOWNSTREAM_STATES,
                id="guard_skipped-resettable",
            ),
            pytest.param(
                RecordState.CASCADE_SKIPPED, CASCADE_BLOCKING_STATES, id="cascade_skipped-blocks"
            ),
            pytest.param(RecordState.FAILED, CASCADE_BLOCKING_STATES, id="failed-blocks"),
            pytest.param(RecordState.EXHAUSTED, CASCADE_BLOCKING_STATES, id="exhausted-blocks"),
        ],
    )
    def test_state_belongs_to_its_category(self, state, category):
        assert state in category
