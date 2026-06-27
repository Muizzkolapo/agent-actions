"""Regression test for VIOL-0031.

`_handle_exhausted_policy` crashed with ``AttributeError`` when
``agent_config["retry"]`` was explicitly ``None`` (the YAML shape
produced by a bare ``retry:`` key with no body), because
``.get("retry", {})`` only substitutes the default when the key is
missing — not when it is present-but-None.

The fix coalesces a present-but-None retry block to an empty dict
so the documented ``on_exhausted=return_last`` default is applied
and the ``exhausted`` tombstone reaches the disposition table.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingResult


def _exhausted_result() -> ProcessingResult:
    """Smallest result that exercises the exhausted branch."""
    return ProcessingResult.exhausted(
        error="forced failure for regression test",
        source_guid="sg-uat-0031",
        input_record={"value": "x"},
    )


def test_handle_exhausted_policy_tolerates_retry_explicitly_none():
    """``agent_config={"retry": None}`` must default to ``return_last``.

    Before VIOL-0031, this raised ``AttributeError: 'NoneType' object has
    no attribute 'get'`` at ``result_collector.py:907`` and the
    ``exhausted`` tombstone never reached the disposition table.
    """
    with patch("agent_actions.processing.result_collector.logger") as mock_logger:
        ResultCollector._handle_exhausted_policy(
            results=[_exhausted_result()],
            agent_config={"retry": None},
            agent_name="always_fail",
            storage_backend=None,
        )

    assert mock_logger.info.called, "expected INFO log from return_last policy"
    assert not mock_logger.warning.called, "raise-path warning must not fire for the default policy"


def test_handle_exhausted_policy_tolerates_retry_key_missing():
    """``agent_config`` without a ``retry`` key continues to work."""
    with patch("agent_actions.processing.result_collector.logger") as mock_logger:
        ResultCollector._handle_exhausted_policy(
            results=[_exhausted_result()],
            agent_config={},
            agent_name="always_fail",
            storage_backend=None,
        )
    assert mock_logger.info.called


def test_handle_exhausted_policy_raise_still_honored():
    """A real ``on_exhausted=raise`` must still raise — the guard
    must not mask the raise policy."""
    from agent_actions.errors import AgentActionsError

    with pytest.raises(AgentActionsError):
        ResultCollector._handle_exhausted_policy(
            results=[_exhausted_result()],
            agent_config={"retry": {"on_exhausted": "raise"}},
            agent_name="always_fail",
            storage_backend=None,
        )
