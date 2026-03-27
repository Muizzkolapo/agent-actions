"""Tests for RunMode enum boundary behavior."""

import pytest

from agent_actions.config.types import RunMode


class TestRunModeValid:
    """Valid RunMode values are accepted (case-insensitive)."""

    def test_lowercase_online(self):
        assert RunMode("online") is RunMode.ONLINE

    def test_lowercase_batch(self):
        assert RunMode("batch") is RunMode.BATCH

    def test_uppercase_online(self):
        assert RunMode("ONLINE") is RunMode.ONLINE

    def test_uppercase_batch(self):
        assert RunMode("BATCH") is RunMode.BATCH

    def test_mixed_case(self):
        assert RunMode("Online") is RunMode.ONLINE
        assert RunMode("Batch") is RunMode.BATCH


class TestRunModeInvalid:
    """Invalid RunMode values raise ValueError."""

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            RunMode("invalid")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            RunMode("")

    def test_realtime_rejected(self):
        """'realtime' is not a valid RunMode — it was deprecated and removed."""
        with pytest.raises(ValueError):
            RunMode("realtime")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            RunMode(None)
