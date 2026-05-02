"""Tests for derive_disposition — RecordState to storage disposition mapping."""

import pytest

from agent_actions.record.disposition import derive_disposition
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import Disposition


class TestDeriveDisposition:
    """Every RecordState maps to exactly one Disposition."""

    def test_processed_maps_to_success(self):
        assert derive_disposition({"_state": "processed"}) == Disposition.SUCCESS.value

    def test_committed_maps_to_success(self):
        assert derive_disposition({"_state": "committed"}) == Disposition.SUCCESS.value

    def test_guard_skipped_maps_to_passthrough(self):
        assert derive_disposition({"_state": "guard_skipped"}) == Disposition.PASSTHROUGH.value

    def test_cascade_skipped_maps_to_unprocessed(self):
        assert derive_disposition({"_state": "cascade_skipped"}) == Disposition.UNPROCESSED.value

    def test_guard_deferred_maps_to_deferred(self):
        assert derive_disposition({"_state": "guard_deferred"}) == Disposition.DEFERRED.value

    def test_failed_maps_to_failed(self):
        assert derive_disposition({"_state": "failed"}) == Disposition.FAILED.value

    def test_exhausted_maps_to_exhausted(self):
        assert derive_disposition({"_state": "exhausted"}) == Disposition.EXHAUSTED.value

    def test_active_maps_to_passthrough(self):
        assert derive_disposition({"_state": "active"}) == Disposition.PASSTHROUGH.value

    def test_all_states_covered(self):
        """Every RecordState has a mapping — no KeyError."""
        for state in RecordState:
            result = derive_disposition({"_state": state.value})
            assert isinstance(result, str)

    def test_missing_state_raises(self):
        with pytest.raises(KeyError):
            derive_disposition({"content": "no state"})

    def test_invalid_state_raises(self):
        with pytest.raises(ValueError):
            derive_disposition({"_state": "bogus"})
