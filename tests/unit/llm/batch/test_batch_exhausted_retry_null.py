"""Regression tests for VIOL-0031 — sibling fix in the batch path.

``BatchResultStrategy._build_exhausted_passthrough`` mirrors the
online-path bug fixed in ``processing/result_collector.py``:
``ctx.agent_config.get("retry", {}).get("on_exhausted", "return_last")``
crashed when either ``retry:`` or ``on_exhausted:`` was a bare YAML key
(parsed as ``None``). The batch path is strictly less tolerant than the
online path — ``OnExhaustedPolicy(None)`` raises ``ValueError`` (the
enum has only ``RETURN_LAST`` and ``RAISE``), so a bare
``on_exhausted:`` blows up the batch result pass before any exhausted
tombstone reaches storage. Both levels are coalesced with ``or``.
"""

import pytest

from agent_actions.llm.batch.core.batch_constants import OnExhaustedPolicy
from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.processing.types import (
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)


def _make_recovery(custom_id: str) -> dict[str, RecoveryMetadata]:
    return {
        custom_id: RecoveryMetadata(
            retry=RetryMetadata(
                attempts=2,
                failures=2,
                succeeded=False,
                reason="api_error",
            )
        )
    }


@pytest.mark.parametrize(
    "agent_config",
    [
        pytest.param({"retry": None}, id="retry-explicitly-none"),
        pytest.param({"retry": {"on_exhausted": None}}, id="on-exhausted-explicitly-none"),
        pytest.param({}, id="retry-key-missing"),
    ],
)
def test_build_exhausted_passthrough_coalesces_null_yaml_values(agent_config):
    """Bare YAML keys (``retry:`` and ``on_exhausted:``) both parse as
    ``None`` and previously crashed on the next ``.get(...)`` call. The
    function must default to ``RETURN_LAST`` and produce an
    ``EXHAUSTED`` tombstone the caller can route to storage."""
    custom_id = "rec_uat_0031"
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={},
        output_directory=None,
        agent_config=agent_config,
        exhausted_recovery=_make_recovery(custom_id),
    )
    strategy = BatchResultStrategy()

    result = strategy._build_exhausted_passthrough(
        ctx,
        custom_id=custom_id,
        original_row={"value": "x"},
        action_name="always_fail",
        source_guid="sg-uat-0031",
        record_index=0,
    )

    # Shape assertion (not just truthiness): a tombstone item must be
    # attached and carry the source_guid so the disposition writer can
    # route it.
    assert result.status is ProcessingStatus.EXHAUSTED
    assert result.source_guid == "sg-uat-0031"
    assert len(result.data) == 1
    assert result.data[0].get("source_guid") == "sg-uat-0031"


def test_build_exhausted_passthrough_raise_still_honored():
    """``on_exhausted=raise`` must still raise — the coalesce must not
    mask the explicit raise policy."""
    custom_id = "rec_uat_0031_raise"
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={},
        output_directory=None,
        agent_config={"retry": {"on_exhausted": OnExhaustedPolicy.RAISE.value}},
        exhausted_recovery=_make_recovery(custom_id),
    )
    strategy = BatchResultStrategy()

    with pytest.raises(RuntimeError, match="Retry exhausted"):
        strategy._build_exhausted_passthrough(
            ctx,
            custom_id=custom_id,
            original_row={"value": "x"},
            action_name="always_fail",
            source_guid="sg-uat-0031",
            record_index=0,
        )
