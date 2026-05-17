"""Phase 3: Batch retrieve correctness tests.

U-2.A: LLM output must win over passthrough on key collision.
U-2.D: FAILED records must appear in output, not vanish.
"""

import copy
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.types import ProcessingResult, ProcessingStatus
from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def strategy() -> BatchResultStrategy:
    """BatchResultStrategy instance for testing."""
    return BatchResultStrategy()


def _build_context_map_row(
    target_id: str,
    *,
    filter_status: FilterStatus | None = None,
    passthrough_fields: dict[str, Any] | None = None,
    skip_reason: str | None = None,
    error: str | None = None,
    content: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a context_map row with batch metadata stamped."""
    row: dict[str, Any] = {
        "target_id": target_id,
        "source_guid": f"sg-{target_id}",
        "content": content or {"text": f"content for {target_id}"},
    }
    if filter_status is not None:
        BatchContextMetadata.set_filter_status(row, filter_status)
    if passthrough_fields is not None:
        BatchContextMetadata.set_passthrough_fields(row, passthrough_fields)
    if skip_reason is not None:
        BatchContextMetadata.set_skip_reason(row, skip_reason)
    return row


def _make_batch_result(custom_id: str, content: dict[str, Any]) -> BatchResult:
    """Build a BatchResult with the given content."""
    result = MagicMock(spec=BatchResult)
    result.custom_id = custom_id
    result.content = content
    result.error = None
    result.success = True
    result.metadata = {}
    result.recovery_metadata = None
    return result


def _make_ctx(
    batch_results: list[BatchResult],
    context_map: dict[str, Any],
    agent_config: dict[str, Any] | None = None,
) -> BatchProcessingContext:
    """Build a BatchProcessingContext with reconciler wired."""
    ctx = BatchProcessingContext(
        batch_results=batch_results,
        context_map=context_map,
        output_directory="/tmp/test",
        agent_config=agent_config or {"action_name": "test_action"},
    )
    ctx.reconciler = BatchResultReconciler(context_map)
    return ctx


# ===========================================================================
# U-2.A: LLM output must win over passthrough on key collision
# ===========================================================================


class TestMergeOrder:
    """U-2.A: LLM output must win over passthrough on key collision."""

    def test_llm_wins_on_passthrough_collision(self, strategy: BatchResultStrategy) -> None:
        """When passthrough and LLM have same key, LLM value is kept."""
        # Passthrough has "summary" — same key the LLM will produce.
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                passthrough_fields={"summary": "Original passthrough value", "extra_field": "kept"},
            ),
        }
        llm_result = _make_batch_result("t-001", {"summary": "LLM generated this", "score": 0.95})

        ctx = _make_ctx([llm_result], context_map)
        results = strategy.process(
            batch_results=ctx.batch_results,
            context_map=ctx.context_map,
            output_directory=ctx.output_directory,
            agent_config=ctx.agent_config,
        )

        assert len(results) == 1
        result = results[0]
        assert result.status == ProcessingStatus.SUCCESS

        # Data items are {source_guid, content: {<existing>, <action_name>: {<merged>}}, target_id}.
        # The passthrough merge happens BEFORE version_merge wraps output under action_name.
        # So the merged fields live inside content[action_name].
        data_item = result.data[0]
        action_ns = data_item["content"]["test_action"]

        # LLM value must win on collision
        assert action_ns["summary"] == "LLM generated this", (
            f"LLM value should win on collision, got action_ns={action_ns}"
        )
        assert action_ns["score"] == 0.95

    def test_passthrough_fills_gaps(self, strategy: BatchResultStrategy) -> None:
        """Passthrough fields that don't collide with LLM output are preserved."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                passthrough_fields={"category": "finance", "region": "US"},
            ),
        }
        llm_result = _make_batch_result("t-001", {"summary": "LLM output", "score": 0.8})

        ctx = _make_ctx([llm_result], context_map)
        results = strategy.process(
            batch_results=ctx.batch_results,
            context_map=ctx.context_map,
            output_directory=ctx.output_directory,
            agent_config=ctx.agent_config,
        )

        assert len(results) == 1
        data_item = results[0].data[0]
        action_ns = data_item["content"]["test_action"]

        # Non-colliding passthrough fields should be present in the action namespace
        assert action_ns.get("category") == "finance", (
            f"Non-colliding passthrough field missing: action_ns={action_ns}"
        )
        assert action_ns.get("region") == "US"

    def test_collision_logged(self, strategy: BatchResultStrategy, caplog: pytest.LogCaptureFixture) -> None:
        """Key collisions between passthrough and LLM output are logged."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                passthrough_fields={"summary": "will collide"},
            ),
        }
        llm_result = _make_batch_result("t-001", {"summary": "LLM wins"})

        ctx = _make_ctx([llm_result], context_map)
        with caplog.at_level(logging.INFO):
            strategy.process(
                batch_results=ctx.batch_results,
                context_map=ctx.context_map,
                output_directory=ctx.output_directory,
                agent_config=ctx.agent_config,
            )

        collision_logged = any("summary" in r.message for r in caplog.records)
        assert collision_logged, (
            "Collision between passthrough and LLM key 'summary' should be logged"
        )

    def test_framework_fields_not_logged_as_collision(
        self, strategy: BatchResultStrategy, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Framework fields (target_id, _state, etc.) should not be logged as collisions."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                passthrough_fields={"target_id": "t-001", "summary": "will collide"},
            ),
        }
        llm_result = _make_batch_result("t-001", {"summary": "LLM wins", "target_id": "t-001"})

        ctx = _make_ctx([llm_result], context_map)
        with caplog.at_level(logging.INFO):
            strategy.process(
                batch_results=ctx.batch_results,
                context_map=ctx.context_map,
                output_directory=ctx.output_directory,
                agent_config=ctx.agent_config,
            )

        # target_id is a framework field — should NOT be logged as collision
        for record in caplog.records:
            if "target_id" in record.message and "collision" in record.message.lower():
                pytest.fail(
                    f"Framework field 'target_id' logged as collision: {record.message}"
                )


# ===========================================================================
# U-2.D: FAILED records must appear in output, not vanish
# ===========================================================================


class TestFailedRecordReconciliation:
    """U-2.D: FAILED records must appear in output, not vanish."""

    def test_failed_records_in_output(self, strategy: BatchResultStrategy) -> None:
        """Records with FilterStatus.FAILED in context_map must appear in final output."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
            ),
            "t-002": _build_context_map_row(
                "t-002",
                filter_status=FilterStatus.FAILED,
            ),
        }
        # Only t-001 returned by provider (t-002 was never submitted — it failed prep)
        provider_results = [
            _make_batch_result("t-001", {"summary": "success"}),
        ]

        ctx = _make_ctx(provider_results, context_map)
        results = strategy.process(
            batch_results=ctx.batch_results,
            context_map=ctx.context_map,
            output_directory=ctx.output_directory,
            agent_config=ctx.agent_config,
        )

        # t-002 must appear in output
        result_target_ids = set()
        for r in results:
            for item in r.data:
                tid = item.get("target_id")
                if tid:
                    result_target_ids.add(tid)
            if r.source_guid and r.source_guid.startswith("sg-"):
                # Extract target_id from source_guid convention
                pass

        # Also check via source_guid
        result_source_guids = {r.source_guid for r in results}

        assert "sg-t-002" in result_source_guids or "t-002" in result_target_ids, (
            f"FAILED record t-002 must appear in output. "
            f"Got source_guids={result_source_guids}, target_ids={result_target_ids}"
        )

    def test_failed_record_has_failed_status(self, strategy: BatchResultStrategy) -> None:
        """FAILED record in output must have a failed/error status, not SUCCESS."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.FAILED,
            ),
        }
        # No provider results — all records failed prep
        results = strategy.process(
            batch_results=[],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config={"action_name": "test_action"},
        )

        assert len(results) >= 1, "FAILED record must produce output"
        failed_result = results[0]
        assert failed_result.status in (ProcessingStatus.FAILED, ProcessingStatus.UNPROCESSED), (
            f"FAILED record should have FAILED or UNPROCESSED status, got {failed_result.status}"
        )

    def test_no_duplicate_records(self, strategy: BatchResultStrategy) -> None:
        """FAILED records must not produce duplicate entries in output."""
        context_map = {
            "t-001": _build_context_map_row("t-001", filter_status=FilterStatus.INCLUDED),
            "t-002": _build_context_map_row("t-002", filter_status=FilterStatus.FAILED),
            "t-003": _build_context_map_row("t-003", filter_status=FilterStatus.SKIPPED, skip_reason="guard_skip"),
        }
        provider_results = [
            _make_batch_result("t-001", {"summary": "success"}),
        ]

        ctx = _make_ctx(provider_results, context_map)
        results = strategy.process(
            batch_results=ctx.batch_results,
            context_map=ctx.context_map,
            output_directory=ctx.output_directory,
            agent_config=ctx.agent_config,
        )

        # Collect all source_guids — no duplicates allowed
        source_guids = [r.source_guid for r in results if r.source_guid]
        assert len(source_guids) == len(set(source_guids)), (
            f"Duplicate source_guids in output: {source_guids}"
        )

    def test_failed_record_has_error_reason(self, strategy: BatchResultStrategy) -> None:
        """FAILED record must carry the error reason from prep failure."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.FAILED,
            ),
        }
        # Stamp skip_reason to simulate prep failure reason
        BatchContextMetadata.set_skip_reason(context_map["t-001"], "prep_failed")

        results = strategy.process(
            batch_results=[],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config={"action_name": "test_action"},
        )

        assert len(results) >= 1, "FAILED record must produce output"
        failed_result = results[0]
        # Must have an error or skip_reason indicating why it failed
        has_reason = (
            failed_result.error is not None
            or failed_result.skip_reason is not None
        )
        assert has_reason, (
            f"FAILED record must carry error reason. "
            f"error={failed_result.error}, skip_reason={failed_result.skip_reason}"
        )
