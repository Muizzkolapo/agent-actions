"""Tests for version_correlation_id propagation in BatchResultStrategy._process_successful_result().

Verifies that structured_items built from the original_row carry version_correlation_id
before being passed to the enrichment pipeline.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.processing.record_helpers import carry_framework_fields


def _make_context(original_row: dict, agent_config: dict | None = None) -> BatchProcessingContext:
    reconciler = MagicMock()
    reconciler.get_record_by_id.return_value = original_row
    reconciler.get_source_guid.return_value = original_row.get("source_guid", "g1")
    reconciler.get_record_index.return_value = 0

    context_map = {"custom-id-1": original_row}
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map=context_map,
        output_directory="/tmp/out",
        agent_config=agent_config or {"agent_type": "summarize", "action_name": "summarize"},
    )
    ctx.reconciler = reconciler
    return ctx


def _make_batch_result(custom_id: str = "custom-id-1", content: object = None):
    result = MagicMock()
    result.custom_id = custom_id
    result.content = content or {"summary": "short"}
    return result


@contextmanager
def _capture_structured_items():
    """Intercept carry_framework_fields to observe structured_items mid-flight."""
    captured: list = []

    def capturing_carry(src, dest, fields=None):
        captured.append(dest)
        return carry_framework_fields(src, dest, fields=fields)

    with patch(
        "agent_actions.llm.batch.processing.batch_result_strategy.carry_framework_fields",
        side_effect=capturing_carry,
    ):
        yield captured


class TestBatchVersionCorrelationIdPropagation:
    def test_version_correlation_id_carried_from_original_row(self):
        """Structured items must carry version_correlation_id from original_row."""
        original_row = {
            "source_guid": "g1",
            "target_id": "t1",
            "version_correlation_id": "vcid-batch-original",
            "content": {"source": {"text": "hello"}},
        }
        ctx = _make_context(original_row)
        strategy = BatchResultStrategy()

        with _capture_structured_items() as captured:
            try:
                strategy._process_successful_result(ctx, _make_batch_result(), "custom-id-1")
            except Exception:
                pass  # enrichment pipeline may fail without full context; we only need items

        assert captured, "carry_framework_fields was never called"
        for item in captured:
            assert item.get("version_correlation_id") == "vcid-batch-original", (
                f"expected vcid-batch-original in {item}"
            )

    def test_no_version_correlation_id_when_absent_in_original_row(self):
        """Items must not acquire version_correlation_id when original_row lacks it."""
        original_row = {
            "source_guid": "g1",
            "target_id": "t1",
            "content": {"source": {"text": "hello"}},
        }
        ctx = _make_context(original_row)
        strategy = BatchResultStrategy()

        with _capture_structured_items() as captured:
            try:
                strategy._process_successful_result(ctx, _make_batch_result(), "custom-id-1")
            except Exception:
                pass

        for item in captured:
            assert "version_correlation_id" not in item, (
                f"unexpected version_correlation_id in {item}"
            )
