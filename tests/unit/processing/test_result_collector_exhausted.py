"""Regression tests for null YAML retry/exhausted config handling.

`_handle_exhausted_policy` previously crashed with ``AttributeError`` when
``agent_config["retry"]`` was explicitly ``None`` (the YAML shape produced
by a bare ``retry:`` key with no body): ``.get("retry", {})`` only
substitutes the default when the key is missing, not when it is
present-but-None. The same antipattern lived one level deeper at
``retry_config.get("on_exhausted", "return_last")``, where a bare
``on_exhausted:`` (``None``) similarly bypassed the default.

The fix coalesces both with ``or`` so the documented
``on_exhausted=return_last`` default is applied and the ``exhausted``
tombstone reaches storage.
"""

from unittest.mock import patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import ProcessingResult


def _exhausted_result() -> ProcessingResult:
    """Smallest result that exercises the exhausted branch."""
    return ProcessingResult.exhausted(
        error="forced failure for regression test",
        source_guid="sg-uat-0031",
        input_record={"value": "x"},
    )


@pytest.mark.parametrize(
    "agent_config,expected_policy_in_log",
    [
        pytest.param({"retry": None}, "return_last", id="retry-explicitly-none"),
        pytest.param(
            {"retry": {"on_exhausted": None}}, "return_last", id="on-exhausted-explicitly-none"
        ),
        pytest.param({"retry": {}}, "return_last", id="retry-empty-dict"),
    ],
)
def test_handle_exhausted_policy_coalesces_null_yaml_values(agent_config, expected_policy_in_log):
    """Bare YAML keys produce ``None``; both levels must coalesce to the
    documented ``return_last`` default rather than crashing or logging
    ``on_exhausted=None``.

    Previously the outer level (``retry: None``) raised
    ``AttributeError`` at ``result_collector.py:907``. Code review of the
    fix surfaced the same antipattern one level deeper, where
    ``on_exhausted: None`` silently logged ``on_exhausted=None`` instead
    of applying the default — fixed in the same PR.
    """
    with patch("agent_actions.processing.result_collector.logger") as mock_logger:
        ResultCollector._handle_exhausted_policy(
            results=[_exhausted_result()],
            agent_config=agent_config,
            agent_name="always_fail",
            storage_backend=None,
        )

    # The return_last branch logs exactly one INFO carrying the resolved
    # policy. Pinning the format string and the policy substitution catches
    # both the AttributeError regression and the misleading-None-log
    # regression in one assertion.
    mock_logger.info.assert_called_once()
    call_args = mock_logger.info.call_args.args
    fmt, *substitutions = call_args
    assert "%s" in fmt
    assert expected_policy_in_log in substitutions


def test_handle_exhausted_policy_raise_still_honored():
    """A real ``on_exhausted=raise`` must still raise — the ``or`` coalesce
    must not mask the raise policy."""
    with pytest.raises(AgentActionsError):
        ResultCollector._handle_exhausted_policy(
            results=[_exhausted_result()],
            agent_config={"retry": {"on_exhausted": "raise"}},
            agent_name="always_fail",
            storage_backend=None,
        )
