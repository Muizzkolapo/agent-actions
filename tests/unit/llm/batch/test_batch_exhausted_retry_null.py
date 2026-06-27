"""Regression test for VIOL-0031 — sibling fix in the batch path.

`BatchResultStrategy._build_exhausted_passthrough` previously crashed
with ``AttributeError`` when ``agent_config["retry"]`` was explicitly
``None`` (a bare ``retry:`` YAML key). The two-line
``.get("retry", {}).get("on_exhausted", ...)`` sequence mirrors the
online path fixed in ``processing/result_collector.py`` and shares the
same root cause: ``.get("retry", {})`` does not substitute the default
when the key is present-but-None.
"""

from __future__ import annotations

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


def test_build_exhausted_passthrough_tolerates_retry_explicitly_none():
    """``agent_config={"retry": None}`` must default to RETURN_LAST."""
    custom_id = "rec_uat_0031"
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={},
        output_directory=None,
        agent_config={"retry": None},
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

    assert result.status is ProcessingStatus.EXHAUSTED
    assert result.source_guid == "sg-uat-0031"
    assert result.data, "exhausted tombstone item should be attached"
