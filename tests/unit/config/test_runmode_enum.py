"""Tests for RunMode enum boundary behavior."""

import pytest

from agent_actions.config.types import RunMode


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("online", RunMode.ONLINE, id="lowercase-online"),
        pytest.param("batch", RunMode.BATCH, id="lowercase-batch"),
        pytest.param("ONLINE", RunMode.ONLINE, id="uppercase-online"),
        pytest.param("BATCH", RunMode.BATCH, id="uppercase-batch"),
        pytest.param("Online", RunMode.ONLINE, id="mixed-case-online"),
        pytest.param("Batch", RunMode.BATCH, id="mixed-case-batch"),
    ],
)
def test_valid_value_is_accepted_case_insensitively(raw, expected):
    assert RunMode(raw) is expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("invalid", id="invalid"),
        pytest.param("", id="empty"),
        # deprecated and removed
        pytest.param("realtime", id="realtime"),
        pytest.param(None, id="none"),
    ],
)
def test_invalid_value_raises(raw):
    with pytest.raises(ValueError):
        RunMode(raw)
