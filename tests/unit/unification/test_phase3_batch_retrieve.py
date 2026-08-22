"""Phase 3: Batch retrieve correctness tests.

U-2.A: LLM output must win over passthrough on key collision.
U-2.D: FAILED records must appear in output, not vanish.
"""

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
from agent_actions.processing.types import ProcessingStatus

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
    """U-2.A: passthrough lands at content level; the action namespace is never overwritten."""

    def test_action_namespace_never_overwritten_by_passthrough(
        self, strategy: BatchResultStrategy
    ) -> None:
        """A passthrough namespace colliding with the action name is skipped."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                passthrough_fields={"test_action": {"summary": "Original passthrough value"}},
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

        action_ns = result.data[0]["content"]["test_action"]
        assert action_ns["summary"] == "LLM generated this", (
            f"LLM output must win over a same-named passthrough namespace, got {action_ns}"
        )
        assert action_ns["score"] == 0.95

    def test_passthrough_namespaces_land_at_content_level(
        self, strategy: BatchResultStrategy
    ) -> None:
        """Namespaced passthrough fields become siblings of the action namespace."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                passthrough_fields={"classify": {"category": "finance", "region": "US"}},
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
        content = results[0].data[0]["content"]
        assert content.get("classify") == {"category": "finance", "region": "US"}, (
            f"Passthrough namespace missing at content level: {content}"
        )
        assert "classify" not in content["test_action"], (
            "Passthrough namespace must not be nested inside the action output"
        )
        assert content["test_action"]["summary"] == "LLM output"

    def test_existing_content_namespace_wins_per_field(self, strategy: BatchResultStrategy) -> None:
        """A namespace already in record content keeps its values; passthrough fills gaps."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                passthrough_fields={"classify": {"category": "stale", "region": "US"}},
                content={"classify": {"category": "finance"}},
            ),
        }
        llm_result = _make_batch_result("t-001", {"summary": "LLM output"})

        ctx = _make_ctx([llm_result], context_map)
        results = strategy.process(
            batch_results=ctx.batch_results,
            context_map=ctx.context_map,
            output_directory=ctx.output_directory,
            agent_config=ctx.agent_config,
        )

        content = results[0].data[0]["content"]
        assert content["classify"]["category"] == "finance", (
            "Existing content value must win over the passthrough copy"
        )
        assert content["classify"]["region"] == "US", (
            "Passthrough must fill fields missing from the existing namespace"
        )

    def test_non_dict_passthrough_entries_ignored(
        self, strategy: BatchResultStrategy, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Framework fields (target_id, _state, etc.) are non-namespaced and are not merged."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                passthrough_fields={"target_id": "t-001", "summary": "flat entry"},
            ),
        }
        llm_result = _make_batch_result("t-001", {"summary": "LLM wins", "target_id": "t-001"})

        ctx = _make_ctx([llm_result], context_map)
        with caplog.at_level(logging.INFO):
            results = strategy.process(
                batch_results=ctx.batch_results,
                context_map=ctx.context_map,
                output_directory=ctx.output_directory,
                agent_config=ctx.agent_config,
            )

        content = results[0].data[0]["content"]
        assert content["test_action"]["summary"] == "LLM wins"
        assert "summary" not in content, "Flat passthrough entries must not leak to content level"

        # target_id is a framework field — should NOT be logged as collision
        for record in caplog.records:
            if "target_id" in record.message and "collision" in record.message.lower():
                pytest.fail(f"Framework field 'target_id' logged as collision: {record.message}")


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

        # t-002 must appear in output (check via source_guid)
        result_source_guids = {r.source_guid for r in results}
        assert "sg-t-002" in result_source_guids, (
            f"FAILED record t-002 must appear in output. Got source_guids={result_source_guids}"
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

        assert len(results) == 1, "FAILED record must produce exactly one output"
        failed_result = results[0]
        assert failed_result.status == ProcessingStatus.FAILED, (
            f"FAILED record must have FAILED status, got {failed_result.status}"
        )

    def test_no_duplicate_records(self, strategy: BatchResultStrategy) -> None:
        """FAILED records must not produce duplicate entries in output."""
        context_map = {
            "t-001": _build_context_map_row("t-001", filter_status=FilterStatus.INCLUDED),
            "t-002": _build_context_map_row("t-002", filter_status=FilterStatus.FAILED),
            "t-003": _build_context_map_row(
                "t-003", filter_status=FilterStatus.SKIPPED, skip_reason="guard_skip"
            ),
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

        assert len(results) == 1, "FAILED record must produce exactly one output"
        failed_result = results[0]
        assert failed_result.error == "prep_failed"
        assert failed_result.skip_reason == "prep_failed"

    def test_failed_record_defaults_to_prep_failed_reason(
        self, strategy: BatchResultStrategy
    ) -> None:
        """FAILED record without skip_reason falls back to PREP_FAILED constant."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.FAILED,
                # No skip_reason set — should fall back to PREP_FAILED
            ),
        }
        results = strategy.process(
            batch_results=[],
            context_map=context_map,
            output_directory="/tmp/test",
            agent_config={"action_name": "test_action"},
        )

        assert len(results) == 1
        failed_result = results[0]
        assert failed_result.error == "prep_failed", (
            f"Should fall back to PREP_FAILED constant, got error={failed_result.error}"
        )
        assert failed_result.skip_reason == "prep_failed"


# ===========================================================================
# Edge cases
# ===========================================================================


class TestPassthroughEdgeCases:
    """Edge cases for passthrough merge logic."""

    def test_no_passthrough_fields_is_noop(self, strategy: BatchResultStrategy) -> None:
        """INCLUDED record with no passthrough_fields — merge is skipped cleanly."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                # No passthrough_fields
            ),
        }
        llm_result = _make_batch_result("t-001", {"summary": "LLM output"})

        ctx = _make_ctx([llm_result], context_map)
        results = strategy.process(
            batch_results=ctx.batch_results,
            context_map=ctx.context_map,
            output_directory=ctx.output_directory,
            agent_config=ctx.agent_config,
        )

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.SUCCESS
        action_ns = results[0].data[0]["content"]["test_action"]
        assert action_ns["summary"] == "LLM output"

    def test_empty_passthrough_fields_is_noop(self, strategy: BatchResultStrategy) -> None:
        """INCLUDED record with empty passthrough_fields dict — no extra keys added."""
        context_map = {
            "t-001": _build_context_map_row(
                "t-001",
                filter_status=FilterStatus.INCLUDED,
                passthrough_fields={},
            ),
        }
        llm_result = _make_batch_result("t-001", {"summary": "LLM output"})

        ctx = _make_ctx([llm_result], context_map)
        results = strategy.process(
            batch_results=ctx.batch_results,
            context_map=ctx.context_map,
            output_directory=ctx.output_directory,
            agent_config=ctx.agent_config,
        )

        assert len(results) == 1
        action_ns = results[0].data[0]["content"]["test_action"]
        assert action_ns == {"summary": "LLM output"}
