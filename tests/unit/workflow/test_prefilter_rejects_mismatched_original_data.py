"""prefilter_by_guard refuses original_data whose length differs from data."""

import pytest

from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard


class TestPrefilterLengthGuard:
    """U-2.E: prefilter_by_guard must raise on original_data/data length mismatch."""

    def test_original_data_length_mismatch_raises(self):
        """If original_data has different length than data, RuntimeError raised."""
        data = [{"content": {"x": 1}}, {"content": {"x": 2}}, {"content": {"x": 3}}]
        original_data = [{"content": {"x": 1}}, {"content": {"x": 2}}]  # only 2 for 3

        with pytest.raises(RuntimeError, match="prefilter_by_guard.*2.*3"):
            prefilter_by_guard(data, {}, "test_agent", original_data=original_data)

    def test_matching_lengths_no_error(self):
        """When original_data matches data length, no error."""
        data = [{"content": {"x": 1}}, {"content": {"x": 2}}]
        original_data = [{"content": {"x": 1, "extra": "a"}}, {"content": {"x": 2, "extra": "b"}}]

        passing, skipped, original_passing, _filtered, _ = prefilter_by_guard(
            data, {}, "test_agent", original_data=original_data
        )
        assert len(passing) == 2
        assert original_passing == original_data
