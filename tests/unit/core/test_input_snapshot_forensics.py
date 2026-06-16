"""Tests for input_snapshot forensics on failure dispositions.

Covers:
- _serialize_snapshot helper (unit)
- EXHAUSTED dispositions writing input_snapshot (consumer)
- _handle_exhausted_policy writing input_snapshot (consumer)
- Batch producer snapshot population (_build_error_result, exhausted, unprocessed)
- File tool producer snapshot population
- Regression: non-terminal dispositions do NOT write input_snapshot
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.processing.result_collector import (
    ResultCollector,
    _serialize_snapshot,
)
from agent_actions.processing.types import (
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)
from tests.conftest import wire_batch_disposition_delegate


def _retry_metadata(attempts: int = 2) -> RecoveryMetadata:
    return RecoveryMetadata(
        retry=RetryMetadata(
            attempts=attempts,
            failures=attempts,
            succeeded=False,
            reason="timeout",
        )
    )


def _make_backend() -> MagicMock:
    backend = MagicMock()
    backend.set_disposition = MagicMock()
    wire_batch_disposition_delegate(backend)
    return backend


# ---------------------------------------------------------------------------
# _serialize_snapshot unit tests
# ---------------------------------------------------------------------------


class TestSerializeSnapshot:
    def test_valid_dict(self):
        result = _serialize_snapshot({"a": 1, "b": "hello"})
        assert json.loads(result) == {"a": 1, "b": "hello"}

    def test_none_input(self):
        assert _serialize_snapshot(None) is None

    def test_empty_dict_returns_none(self):
        assert _serialize_snapshot({}) is None

    def test_non_dict_returns_none(self):
        assert _serialize_snapshot("not a dict") is None  # type: ignore[arg-type]
        assert _serialize_snapshot([1, 2]) is None  # type: ignore[arg-type]

    def test_non_serializable_uses_default_str(self):
        """datetime and other non-JSON types fall back to str via default=str."""
        from datetime import datetime

        dt = datetime(2026, 1, 1, 12, 0, 0)
        result = _serialize_snapshot({"ts": dt, "val": 42})
        assert result is not None
        parsed = json.loads(result)
        assert parsed["val"] == 42
        assert "2026" in parsed["ts"]

    def test_circular_reference_returns_none(self):
        d: dict[str, Any] = {"key": "value"}
        d["self"] = d
        assert _serialize_snapshot(d) is None

    def test_ensure_ascii_false(self):
        result = _serialize_snapshot({"name": "café"})
        assert result is not None
        assert "café" in result  # Not escaped to \\u


# ---------------------------------------------------------------------------
# Consumer: EXHAUSTED main branch writes input_snapshot
# ---------------------------------------------------------------------------


class TestExhaustedMainBranchSnapshot:
    def test_exhausted_writes_input_snapshot_from_source_snapshot(self):
        backend = _make_backend()
        snapshot = {"source_guid": "sg-1", "content": {"field": "data"}}
        exhausted = ProcessingResult.exhausted(
            error="Retry exhausted",
            source_guid="sg-1",
            recovery_metadata=_retry_metadata(),
            source_snapshot=snapshot,
        )
        exhausted.data = [{"source_guid": "sg-1", "content": {}}]

        ResultCollector.collect_results(
            [exhausted],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        call_kwargs = backend.set_disposition.call_args[1]
        assert call_kwargs["input_snapshot"] is not None
        parsed = json.loads(call_kwargs["input_snapshot"])
        assert parsed["content"]["field"] == "data"

    def test_exhausted_writes_input_snapshot_from_input_record_fallback(self):
        backend = _make_backend()
        exhausted = ProcessingResult.exhausted(
            error="Retry exhausted",
            source_guid="sg-2",
            recovery_metadata=_retry_metadata(),
            input_record={"target_id": "t-1", "content": {"x": 1}},
        )
        exhausted.data = [{"source_guid": "sg-2", "content": {}}]

        ResultCollector.collect_results(
            [exhausted],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        call_kwargs = backend.set_disposition.call_args[1]
        assert call_kwargs["input_snapshot"] is not None
        parsed = json.loads(call_kwargs["input_snapshot"])
        assert parsed["target_id"] == "t-1"

    def test_exhausted_no_snapshot_writes_none(self):
        backend = _make_backend()
        exhausted = ProcessingResult.exhausted(
            error="Retry exhausted",
            source_guid="sg-3",
            recovery_metadata=_retry_metadata(),
        )
        exhausted.data = [{"source_guid": "sg-3", "content": {}}]

        ResultCollector.collect_results(
            [exhausted],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        call_kwargs = backend.set_disposition.call_args[1]
        assert call_kwargs["input_snapshot"] is None


# ---------------------------------------------------------------------------
# Consumer: _handle_exhausted_policy writes input_snapshot before raising
# ---------------------------------------------------------------------------


class TestExhaustedRaiseBranchSnapshot:
    def test_handle_exhausted_policy_writes_snapshot_before_raising(self):
        backend = _make_backend()
        snapshot = {"source_guid": "sg-raise", "content": {"prompt": "too long"}}
        exhausted = ProcessingResult.exhausted(
            error="Retry exhausted",
            source_guid="sg-raise",
            recovery_metadata=_retry_metadata(),
            source_snapshot=snapshot,
        )

        agent_config = {"retry": {"on_exhausted": "raise"}}

        with pytest.raises(AgentActionsError):
            ResultCollector.collect_results(
                [exhausted],
                agent_config,
                "agent",
                is_first_stage=True,
                storage_backend=backend,
            )

        call_kwargs = backend.set_disposition.call_args[1]
        assert call_kwargs["input_snapshot"] is not None
        parsed = json.loads(call_kwargs["input_snapshot"])
        assert parsed["content"]["prompt"] == "too long"

    def test_handle_exhausted_policy_no_snapshot_writes_none(self):
        backend = _make_backend()
        exhausted = ProcessingResult.exhausted(
            error="Retry exhausted",
            source_guid="sg-raise-none",
            recovery_metadata=_retry_metadata(),
        )

        agent_config = {"retry": {"on_exhausted": "raise"}}

        with pytest.raises(AgentActionsError):
            ResultCollector.collect_results(
                [exhausted],
                agent_config,
                "agent",
                is_first_stage=True,
                storage_backend=backend,
            )

        call_kwargs = backend.set_disposition.call_args[1]
        assert call_kwargs["input_snapshot"] is None


# ---------------------------------------------------------------------------
# Consumer: FAILED branch still works (refactored to use helper)
# ---------------------------------------------------------------------------


class TestFailedBranchSnapshotRefactor:
    def test_failed_with_snapshot_writes_serialized(self):
        backend = _make_backend()
        snapshot = {"field": "value", "num": 42}
        failed = ProcessingResult.failed(
            error="boom",
            source_guid="sg-f",
            source_snapshot=snapshot,
        )

        ResultCollector.collect_results(
            [failed],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        call_kwargs = backend.set_disposition.call_args[1]
        assert call_kwargs["input_snapshot"] is not None
        parsed = json.loads(call_kwargs["input_snapshot"])
        assert parsed == {"field": "value", "num": 42}

    def test_failed_without_snapshot_writes_none(self):
        backend = _make_backend()
        failed = ProcessingResult.failed(error="boom", source_guid="sg-f2")

        ResultCollector.collect_results(
            [failed],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        call_kwargs = backend.set_disposition.call_args[1]
        assert call_kwargs["input_snapshot"] is None


# ---------------------------------------------------------------------------
# Consumer: both EXHAUSTED write paths produce identical snapshots
# ---------------------------------------------------------------------------


class TestExhaustedBothPathsIdentical:
    def test_same_input_produces_identical_snapshots(self):
        """Default exhaust and on_exhausted=raise produce same input_snapshot."""
        snapshot = {"source_guid": "sg-ident", "content": {"k": "v"}}

        # Path 1: default (return_last) — main branch
        backend1 = _make_backend()
        exhausted1 = ProcessingResult.exhausted(
            error="Retry exhausted",
            source_guid="sg-ident",
            recovery_metadata=_retry_metadata(),
            source_snapshot=dict(snapshot),
        )
        exhausted1.data = [{"source_guid": "sg-ident", "content": {}}]
        ResultCollector.collect_results(
            [exhausted1],
            {"retry": {"on_exhausted": "return_last"}},
            "agent",
            is_first_stage=False,
            storage_backend=backend1,
        )
        snap1 = backend1.set_disposition.call_args[1]["input_snapshot"]

        # Path 2: on_exhausted=raise — _handle_exhausted_policy branch
        backend2 = _make_backend()
        exhausted2 = ProcessingResult.exhausted(
            error="Retry exhausted",
            source_guid="sg-ident",
            recovery_metadata=_retry_metadata(),
            source_snapshot=dict(snapshot),
        )
        with pytest.raises(AgentActionsError):
            ResultCollector.collect_results(
                [exhausted2],
                {"retry": {"on_exhausted": "raise"}},
                "agent",
                is_first_stage=True,
                storage_backend=backend2,
            )
        snap2 = backend2.set_disposition.call_args[1]["input_snapshot"]

        assert snap1 == snap2


# ---------------------------------------------------------------------------
# Regression: non-terminal dispositions do NOT write input_snapshot
# ---------------------------------------------------------------------------


class TestNonTerminalNoSnapshot:
    def test_success_no_input_snapshot(self):
        backend = _make_backend()
        success = ProcessingResult.success(
            data=[{"content": {"v": 1}}],
            source_guid="sg-ok",
        )
        ResultCollector.collect_results(
            [success], {}, "agent", is_first_stage=False, storage_backend=backend
        )
        call_kwargs = backend.set_disposition.call_args[1]
        assert "input_snapshot" not in call_kwargs

    def test_filtered_no_input_snapshot(self):
        backend = _make_backend()
        filtered = ProcessingResult.filtered(source_guid="sg-filt")
        ResultCollector.collect_results(
            [filtered], {}, "agent", is_first_stage=False, storage_backend=backend
        )
        call_kwargs = backend.set_disposition.call_args[1]
        assert "input_snapshot" not in call_kwargs

    def test_unprocessed_no_input_snapshot(self):
        backend = _make_backend()
        unprocessed = ProcessingResult.unprocessed(
            data=[{"content": {}}],
            reason="upstream_unprocessed",
            source_guid="sg-un",
        )
        ResultCollector.collect_results(
            [unprocessed], {}, "agent", is_first_stage=False, storage_backend=backend
        )
        call_kwargs = backend.set_disposition.call_args[1]
        assert "input_snapshot" not in call_kwargs


# ---------------------------------------------------------------------------
# Producer: batch_result_strategy._build_error_result
# ---------------------------------------------------------------------------


class TestBatchErrorResultSnapshot:
    def _make_strategy_and_ctx(self, context_map: dict[str, Any] | None = None):
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
            BatchResultStrategy,
        )
        from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler

        ctx_map = context_map or {
            "cid-1": {"source_guid": "sg-1", "content": {"field": "original_data"}},
        }
        ctx = BatchProcessingContext(
            batch_results=[],
            context_map=ctx_map,
            output_directory=None,
            agent_config={"action_name": "test"},
        )
        ctx.reconciler = BatchResultReconciler(ctx_map)
        return BatchResultStrategy(), ctx

    def test_snapshot_populated_from_reconciler(self):
        strategy, ctx = self._make_strategy_and_ctx()
        result = strategy._build_error_result(ctx, "cid-1", "some error")
        assert result.source_snapshot is not None
        assert result.source_snapshot["source_guid"] == "sg-1"
        assert result.source_snapshot["content"]["field"] == "original_data"

    def test_snapshot_is_defensive_copy(self):
        strategy, ctx = self._make_strategy_and_ctx()
        result = strategy._build_error_result(ctx, "cid-1", "some error")
        # Mutate original in context_map
        ctx.context_map["cid-1"]["content"]["field"] = "MUTATED"
        # Snapshot should be unaffected
        assert result.source_snapshot["content"]["field"] == "original_data"

    def test_missing_record_returns_none_snapshot(self):
        strategy, ctx = self._make_strategy_and_ctx()
        result = strategy._build_error_result(ctx, "cid-missing", "not found")
        assert result.source_snapshot is None

    def test_uses_failed_factory(self):
        strategy, ctx = self._make_strategy_and_ctx()
        result = strategy._build_error_result(ctx, "cid-1", "err")
        assert result.status == ProcessingStatus.FAILED
        assert result.executed is False  # Factory sets this

    def test_data_still_set_for_write_record_dispositions(self):
        strategy, ctx = self._make_strategy_and_ctx()
        result = strategy._build_error_result(ctx, "cid-1", "err", metadata={"k": "v"})
        assert len(result.data) == 1
        assert result.data[0]["error"] == "err"
        assert result.data[0]["source_guid"] == "sg-1"

    def test_recovery_metadata_preserved(self):
        strategy, ctx = self._make_strategy_and_ctx()
        rm = _retry_metadata()
        result = strategy._build_error_result(ctx, "cid-1", "err", recovery_metadata=rm)
        assert result.recovery_metadata is rm
        assert result.data[0]["_recovery"]["retry"]["attempts"] == 2


# ---------------------------------------------------------------------------
# Producer: batch exhausted/unprocessed passthrough snapshots
# ---------------------------------------------------------------------------


class TestBatchPassthroughSnapshots:
    def _make_strategy_and_ctx(self):
        from agent_actions.llm.batch.processing.batch_result_strategy import (
            BatchProcessingContext,
            BatchResultStrategy,
        )
        from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler

        ctx_map = {
            "cid-ex": {"source_guid": "sg-ex", "content": {"field": "exhaust_data"}},
            "cid-un": {"source_guid": "sg-un", "content": {"field": "unproc_data"}},
        }
        ctx = BatchProcessingContext(
            batch_results=[],
            context_map=ctx_map,
            output_directory=None,
            agent_config={"action_name": "test"},
            exhausted_recovery={
                "cid-ex": _retry_metadata(),
            },
        )
        ctx.reconciler = BatchResultReconciler(ctx_map)
        return BatchResultStrategy(), ctx

    def test_exhausted_passthrough_includes_source_snapshot(self):
        strategy, ctx = self._make_strategy_and_ctx()
        result = strategy._build_exhausted_passthrough(
            ctx,
            "cid-ex",
            {"source_guid": "sg-ex", "content": {"field": "exhaust_data"}},
            "test",
            "sg-ex",
            0,
        )
        assert result.source_snapshot is not None
        assert result.source_snapshot["content"]["field"] == "exhaust_data"

    def test_unprocessed_passthrough_includes_source_snapshot(self):
        strategy, ctx = self._make_strategy_and_ctx()
        result = strategy._build_unprocessed_passthrough(
            ctx,
            {"source_guid": "sg-un", "content": {"field": "unproc_data"}},
            "test",
            "sg-un",
            0,
        )
        assert result.source_snapshot is not None
        assert result.source_snapshot["content"]["field"] == "unproc_data"

    def test_exhausted_snapshot_is_copy(self):
        strategy, ctx = self._make_strategy_and_ctx()
        original = {"source_guid": "sg-ex", "content": {"field": "exhaust_data"}}
        result = strategy._build_exhausted_passthrough(
            ctx,
            "cid-ex",
            original,
            "test",
            "sg-ex",
            0,
        )
        original["content"]["field"] = "MUTATED"
        assert result.source_snapshot["content"]["field"] == "exhaust_data"


# ---------------------------------------------------------------------------
# Producer: file_tool snapshot
# ---------------------------------------------------------------------------


class TestFileToolSnapshot:
    def test_failed_result_includes_source_snapshot(self):
        from agent_actions.processing.strategies.file_tool import FileToolStrategy

        strategy = FileToolStrategy()
        records = [
            {"source_guid": "sg-ft", "content": {"field": "tool_input"}},
            {"source_guid": "sg-ft2", "content": {"field": "tool_input2"}},
        ]
        context = MagicMock()
        context.agent_name = "my_tool"
        context.source_data = records
        context.agent_config = {"context_scope": {}}

        with (
            patch(
                "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
                return_value=([], True),
            ),
            patch(
                "agent_actions.processing.strategies.file_tool.is_empty_response",
                return_value=True,
            ),
        ):
            results = strategy.invoke(records, context)

        assert len(results) == 2
        for i, result in enumerate(results):
            assert result.status == ProcessingStatus.FAILED
            assert result.source_snapshot is not None
            assert result.source_snapshot["source_guid"] == records[i]["source_guid"]

    def test_failed_result_single_record_snapshot(self):
        """Single-record failure captures that record's snapshot."""
        from agent_actions.processing.strategies.file_tool import FileToolStrategy

        strategy = FileToolStrategy()
        records = [{"source_guid": "sg-single", "content": {}}]
        context = MagicMock()
        context.agent_name = "my_tool"
        context.source_data = records
        context.agent_config = {"context_scope": {}}

        with (
            patch(
                "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
                return_value=([], True),
            ),
            patch(
                "agent_actions.processing.strategies.file_tool.is_empty_response",
                return_value=True,
            ),
        ):
            results = strategy.invoke(records, context)

        assert results[0].source_snapshot is not None
