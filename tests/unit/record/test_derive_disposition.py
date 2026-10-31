"""Tests for derive_disposition — RecordState to storage disposition mapping."""

import pytest

from agent_actions.record.disposition import derive_disposition
from agent_actions.record.envelope import RecordEnvelopeError
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import Disposition


class TestDeriveDisposition:
    """Every RecordState maps to exactly one Disposition."""

    @pytest.mark.parametrize(
        ("state", "disposition"),
        [
            pytest.param("processed", Disposition.SUCCESS, id="processed-success"),
            # A guard skip answers nothing, so the next run puts the record to the guard again.
            pytest.param("guard_skipped", Disposition.UNPROCESSED, id="guard_skipped-unprocessed"),
            pytest.param(
                "cascade_skipped", Disposition.UNPROCESSED, id="cascade_skipped-unprocessed"
            ),
            pytest.param("failed", Disposition.FAILED, id="failed-failed"),
            pytest.param("exhausted", Disposition.EXHAUSTED, id="exhausted-exhausted"),
            pytest.param("active", Disposition.PASSTHROUGH, id="active-passthrough"),
        ],
    )
    def test_state_maps_to_its_disposition(self, state, disposition):
        assert derive_disposition({"_state": state}) == disposition.value

    def test_all_states_covered(self):
        """Every RecordState has a mapping."""
        for state in RecordState:
            result = derive_disposition({"_state": state.value})
            assert isinstance(result, str)

    def test_missing_state_raises_envelope_error(self):
        with pytest.raises(RecordEnvelopeError, match="no '_state' field"):
            derive_disposition({"content": "no state"})

    def test_invalid_state_raises_envelope_error(self):
        with pytest.raises(RecordEnvelopeError, match="unknown _state value.*bogus"):
            derive_disposition({"_state": "bogus"})
