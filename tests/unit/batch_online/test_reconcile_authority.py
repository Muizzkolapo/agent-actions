"""Phase 6 tests — reconciliation trusts prep as single cascade authority.

U-1.2: Reconciliation must not re-check cascade via _is_cascade_blocked().
After Phase 2 makes context_map trustworthy, get_skip_reason() is the sole
authority for CASCADE decisions during passthrough reconciliation.
"""

from typing import Any

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.record.reasons import (
    BATCH_NOT_RETURNED,
    GUARD_SKIP,
    UPSTREAM_UNPROCESSED,
)
from agent_actions.record.state import RecordState


def _make_ctx(
    original_row: dict[str, Any],
    custom_id: str = "t-001",
) -> BatchProcessingContext:
    """Build a minimal BatchProcessingContext for passthrough testing."""
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={custom_id: original_row},
        output_directory="/tmp/test",
        agent_config={
            "name": "test_action",
            "action_name": "test_action",
            "agent_type": "llm_agent",
        },
    )
    ctx.reconciler = BatchResultReconciler(context_map={custom_id: original_row})
    return ctx


class TestSingleCascadeAuthority:
    """U-1.2: Reconciliation must not re-check cascade — trust prep."""

    def test_no_cascade_blocked_function_exists(self):
        """_is_cascade_blocked must not exist in the module — single authority is prep.

        After Phase 6, the function is deleted entirely. Reconciliation uses
        get_skip_reason() as the sole authority for CASCADE decisions.
        """
        import agent_actions.llm.batch.processing.batch_result_strategy as mod

        assert not hasattr(mod, "_is_cascade_blocked"), (
            "_is_cascade_blocked must be deleted — get_skip_reason() is sole authority"
        )

    def test_prep_skip_reason_is_authority(self):
        """get_skip_reason() provides passthrough reason without re-evaluation."""
        original_row = {
            "target_id": "t-001",
            "_state": RecordState.FAILED.value,
            "content": {"data": "value"},
        }
        BatchContextMetadata.set_filter_status(original_row, FilterStatus.SKIPPED)
        BatchContextMetadata.set_skip_reason(original_row, UPSTREAM_UNPROCESSED)

        ctx = _make_ctx(original_row)
        strategy = BatchResultStrategy()
        result = strategy._build_unprocessed_passthrough(
            ctx, original_row, "test_action", "sg_001", 0
        )

        assert result.skip_reason == UPSTREAM_UNPROCESSED

    def test_cascade_blocked_without_skip_reason_falls_to_default(self):
        """Without skip_reason, cascade-blocked _state should NOT trigger special handling.

        After Phase 6, there is no _is_cascade_blocked fallback.
        Records that somehow bypass prep without skip_reason get BATCH_NOT_RETURNED.
        """
        original_row = {
            "target_id": "t-002",
            "_state": RecordState.CASCADE_SKIPPED.value,
            "content": {},
        }
        # No filter_status, no skip_reason — previously fell back to _is_cascade_blocked

        ctx = _make_ctx(original_row, custom_id="t-002")
        strategy = BatchResultStrategy()
        result = strategy._build_unprocessed_passthrough(
            ctx, original_row, "test_action", "sg_002", 0
        )

        # Single authority: without skip_reason, default is BATCH_NOT_RETURNED
        assert result.skip_reason == BATCH_NOT_RETURNED

    def test_guard_skip_fallback_still_works(self):
        """FilterStatus.SKIPPED without skip_reason still falls back to GUARD_SKIP."""
        original_row = {"target_id": "t-003", "content": {}}
        BatchContextMetadata.set_filter_status(original_row, FilterStatus.SKIPPED)
        # No skip_reason — should fall back to GUARD_SKIP via FilterStatus check

        ctx = _make_ctx(original_row, custom_id="t-003")
        strategy = BatchResultStrategy()
        result = strategy._build_unprocessed_passthrough(
            ctx, original_row, "test_action", "sg_003", 0
        )

        assert result.skip_reason == GUARD_SKIP

    def test_explicit_skip_reason_takes_priority_over_state(self):
        """Even if _state is cascade-blocked, skip_reason from prep wins."""
        original_row = {
            "target_id": "t-004",
            "_state": RecordState.FAILED.value,
            "content": {},
        }
        BatchContextMetadata.set_filter_status(original_row, FilterStatus.SKIPPED)
        BatchContextMetadata.set_skip_reason(original_row, GUARD_SKIP)

        ctx = _make_ctx(original_row, custom_id="t-004")
        strategy = BatchResultStrategy()
        result = strategy._build_unprocessed_passthrough(
            ctx, original_row, "test_action", "sg_004", 0
        )

        # skip_reason from prep wins over _state
        assert result.skip_reason == GUARD_SKIP
