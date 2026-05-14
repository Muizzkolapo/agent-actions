"""ProcessingResult construction unification guards (spec 406).

Each test exercises production code paths and asserts on observable output.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.enrichment import VersionIdEnricher
from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.processing.prepared_task import GuardStatus, PreparedTask
from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)
from agent_actions.record.tracking import TrackedItem

FRESH_VCID = "fresh-vcid-for-test"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _make_context(
    agent_name: str = "test_action",
    **kwargs: Any,
) -> ProcessingContext:
    config: dict[str, Any] = {
        "kind": "llm",
        "agent_type": agent_name,
        "action_name": agent_name,
        "is_versioned_agent": False,
        "workflow_session_id": "session-1",
    }
    return ProcessingContext(agent_config=config, agent_name=agent_name, **kwargs)


def _make_file_context(agent_name: str = "my_file_tool") -> ProcessingContext:
    return ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file"},
        agent_name=agent_name,
    )


def _make_prepared(
    target_id: str = "tid-1",
    source_guid: str = "sg-1",
    guard_status: GuardStatus = GuardStatus.PASSED,
    **kwargs: Any,
) -> PreparedTask:
    return PreparedTask(
        target_id=target_id,
        source_guid=source_guid,
        formatted_prompt="test prompt",
        llm_context={"content": "test"},
        original_content={"field": "value"},
        source_snapshot={"field": "value"},
        guard_status=guard_status,
        **kwargs,
    )


def _make_batch_ctx(
    custom_id: str = "rec_001",
    original_row: dict | None = None,
    action_name: str = "test_action",
) -> BatchProcessingContext:
    if original_row is None:
        original_row = {"source_guid": "sg-001", "content": {"prev": {"x": 1}}}
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={custom_id: original_row},
        output_directory="/tmp/output",
        agent_config={"action_name": action_name, "kind": "llm"},
    )
    ctx.reconciler = BatchResultReconciler(context_map={custom_id: original_row})
    return ctx


def _patch_generator():
    return patch(
        "agent_actions.utils.correlation.VersionIdGenerator.add_version_correlation_id",
        side_effect=lambda item, config, record_index=0, force=False: {
            **item,
            "version_correlation_id": f"{FRESH_VCID}-{record_index}",
        },
    )


# -- T1, T2: file_tool factory switch — exercises FileToolStrategy.invoke() --


class TestFileToolFactorySwitch:
    def test_expansion_via_invoke(self):
        """T1: FileToolStrategy.invoke() returns correct fields on expansion."""
        input_data = [
            {"source_guid": "sg-1", "content": {"prev": {"id": 1}}},
            {"source_guid": "sg-2", "content": {"prev": {"id": 2}}},
        ]
        context = _make_file_context()
        context.source_data = input_data

        # Tool returns 3 items from 2 inputs (expansion)
        tracked_items = [
            TrackedItem({"out": "a"}, source_index=0),
            TrackedItem({"out": "b"}, source_index=0),
            TrackedItem({"out": "c"}, source_index=1),
        ]
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(tracked_items, True),
        ):
            results = FileToolStrategy().invoke(input_data, context)

        result = results[0]
        assert result.status == ProcessingStatus.SUCCESS
        assert len(result.data) == 3
        assert result.is_expansion is True  # 3 > 2
        assert result.executed is True
        assert result.source_mapping is not None
        assert result.source_guid is None  # FILE mode
        assert result.raw_response is not None

    def test_no_expansion_via_invoke(self):
        """T2: is_expansion is False when output count == input count."""
        input_data = [
            {"source_guid": "sg-1", "content": {"prev": {"id": 1}}},
            {"source_guid": "sg-2", "content": {"prev": {"id": 2}}},
        ]
        context = _make_file_context()
        context.source_data = input_data

        tracked_items = [
            TrackedItem({"out": "a"}, source_index=0),
            TrackedItem({"out": "b"}, source_index=1),
        ]
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(tracked_items, True),
        ):
            results = FileToolStrategy().invoke(input_data, context)

        assert results[0].is_expansion is False  # 2 == 2

    def test_executed_false_survives_factory(self):
        """executed=False from tool must survive the factory switch."""
        input_data = [{"source_guid": "sg-1", "content": {"prev": {"id": 1}}}]
        context = _make_file_context()
        context.source_data = input_data

        tracked_items = [TrackedItem({"out": "a"}, source_index=0)]
        with patch(
            "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
            return_value=(tracked_items, False),  # executed=False
        ):
            results = FileToolStrategy().invoke(input_data, context)

        assert results[0].executed is False


# -- T3, T4, T10: target_id carrying via OnlineLLMStrategy.process_record() --


class TestTargetIdCarrying:
    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_first_stage_target_id_on_output(self, mock_fire, mock_get_preparer):
        """T3: first-stage generated target_id appears on output records."""
        prepared = _make_prepared(target_id="generated-uuid-1234")
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response={"output": "result"}, executed=True
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )
        strategy._transform_response = MagicMock(
            return_value=[{"content": {"test": {"output": "result"}}}]
        )

        result = strategy.process_record({"field": "value"}, _make_context())

        assert result.status == ProcessingStatus.SUCCESS
        for record in result.data:
            assert record["target_id"] == "generated-uuid-1234"

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_downstream_target_id_preserved(self, mock_fire, mock_get_preparer):
        """T4: downstream target_id carried through, not regenerated."""
        prepared = _make_prepared(target_id="abc-123")
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response={"output": "result"}, executed=True
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )
        strategy._transform_response = MagicMock(
            return_value=[{"content": {"test": {"output": "result"}}}]
        )

        result = strategy.process_record({"field": "value"}, _make_context())

        assert result.data[0]["target_id"] == "abc-123"

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_cross_record_target_id_isolation(self, mock_fire, mock_get_preparer):
        """T10: sequential processing must not cross-contaminate target_ids."""
        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response={"output": "x"}, executed=True
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )
        strategy._transform_response = MagicMock(
            side_effect=lambda *a, **kw: [{"content": {"test": {"output": "x"}}}]
        )
        context = _make_context()

        # Process record A with target_id AAA
        prepared_a = _make_prepared(target_id="AAA")
        mock_get_preparer.return_value.prepare.return_value = prepared_a
        result_a = strategy.process_record({"id": "a"}, context)

        # Process record B with target_id BBB
        prepared_b = _make_prepared(target_id="BBB")
        mock_get_preparer.return_value.prepare.return_value = prepared_b
        result_b = strategy.process_record({"id": "b"}, context)

        assert result_a.data[0]["target_id"] == "AAA"
        assert result_b.data[0]["target_id"] == "BBB"


# -- T5, T6: skipped() factory signature ------------------------------------


class TestSkippedFactorySignature:
    def test_snapshot_stored(self):
        result = ProcessingResult.skipped(
            passthrough_data=None,
            reason="guard_skip",
            source_snapshot={"field": "val"},
        )
        assert result.source_snapshot == {"field": "val"}

    def test_input_record_stored(self):
        result = ProcessingResult.skipped(
            passthrough_data=None,
            reason="guard_skip",
            input_record={"id": "abc"},
        )
        assert result.input_record == {"id": "abc"}

    def test_both_snapshot_and_input_record_stored(self):
        result = ProcessingResult.skipped(
            passthrough_data={"tombstone": True},
            reason="guard_skip",
            source_snapshot={"snap": "shot"},
            input_record={"rec": "ord"},
        )
        assert result.source_snapshot == {"snap": "shot"}
        assert result.input_record == {"rec": "ord"}

    def test_defaults_to_none(self):
        result = ProcessingResult.skipped(passthrough_data=None, reason="guard_skip")
        assert result.source_snapshot is None
        assert result.input_record is None

    def test_backward_compat_with_all_original_params(self):
        result = ProcessingResult.skipped(
            passthrough_data={"key": "val"},
            reason="guard_block",
            source_guid="guid-123",
        )
        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "guard_block"
        assert result.data == [{"key": "val"}]
        assert result.source_guid == "guid-123"
        assert result.source_snapshot is None
        assert result.input_record is None
        assert result.executed is False

    def test_backward_compat_reason_only(self):
        result = ProcessingResult.skipped(passthrough_data=None, reason="prefilter")
        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "prefilter"
        assert result.data == []
        assert result.source_snapshot is None
        assert result.input_record is None


# -- T7, T8: batch is_expansion + enricher behavior -------------------------


class TestBatchIsExpansion:
    def test_expansion_via_process_successful_result(self):
        """T7: _process_successful_result sets is_expansion and enricher reacts."""
        custom_id = "rec_001"
        original_row = {
            "source_guid": "sg-001",
            "content": {"prev": {"x": 1}},
            "target_id": "tid-batch",
        }
        ctx = _make_batch_ctx(custom_id=custom_id, original_row=original_row)

        # Batch result producing 3 output items from 1 input
        batch_result = BatchResult(
            custom_id=custom_id,
            content=[{"a": 1}, {"b": 2}, {"c": 3}],
            success=True,
        )

        processor = BatchResultStrategy()
        result = processor._process_successful_result(ctx, batch_result, custom_id)

        assert result.is_expansion is True
        assert len(result.data) == 3

        # Enricher produces distinct vcids for expansion
        enrich_ctx = _make_context(record_index=0)
        with _patch_generator():
            enriched = VersionIdEnricher().enrich(result, enrich_ctx)

        vcids = [item["version_correlation_id"] for item in enriched.data]
        assert len(set(vcids)) == 3, f"Expected 3 distinct vcids, got {vcids}"

    def test_no_expansion_via_process_successful_result(self):
        """T8: single-item batch result has is_expansion=False."""
        custom_id = "rec_001"
        original_row = {"source_guid": "sg-001", "content": {"prev": {"x": 1}}}
        ctx = _make_batch_ctx(custom_id=custom_id, original_row=original_row)

        batch_result = BatchResult(
            custom_id=custom_id,
            content={"a": 1},
            success=True,
        )

        processor = BatchResultStrategy()
        result = processor._process_successful_result(ctx, batch_result, custom_id)

        assert result.is_expansion is False
        assert len(result.data) == 1

    def test_no_expansion_preserves_existing_vcid(self):
        items = [
            {"source_guid": "sg1", "content": {"a": 1}, "version_correlation_id": "existing-id"},
        ]
        result = ProcessingResult.success(data=items, source_guid="sg1", is_expansion=False)

        ctx = _make_context(record_index=0)
        with _patch_generator():
            enriched = VersionIdEnricher().enrich(result, ctx)

        assert enriched.data[0]["version_correlation_id"] == "existing-id"


# -- T9: batch error data structure via _build_error_result() ----------------


class TestBatchErrorDataStructure:
    def test_error_result_via_build_error_result(self):
        """T9: _build_error_result() produces the data structure
        write_record_dispositions() depends on."""
        custom_id = "rec_err"
        original_row = {"source_guid": "sg-err", "content": {"data": "x"}}
        ctx = _make_batch_ctx(custom_id=custom_id, original_row=original_row)

        recovery = RecoveryMetadata(
            retry=RetryMetadata(attempts=2, failures=1, succeeded=False, reason="api_error")
        )
        processor = BatchResultStrategy()
        result = processor._build_error_result(
            ctx=ctx,
            custom_id=custom_id,
            error_message="LLM returned invalid JSON",
            metadata={"retry_exhausted": False},
            raw_content='{"broken": json}',
            recovery_metadata=recovery,
        )

        assert result.status == ProcessingStatus.FAILED
        assert len(result.data) == 1

        item = result.data[0]
        assert item["source_guid"] == "sg-err"
        assert isinstance(item["error"], str)
        assert "metadata" in item
        assert "_recovery" in item
        assert isinstance(item["_recovery"], dict)
        assert result.source_snapshot is not None  # deepcopy of original_input


# -- T11: grep audit — no raw constructors for SUCCESS or FAILED -------------


class TestGrepAudit:
    def test_no_raw_constructors_for_success_or_failed(self):
        result = subprocess.run(
            [
                "grep",
                "-rnE",
                r"ProcessingResult\(status=ProcessingStatus\.(SUCCESS|FAILED)",
                "agent_actions/",
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.stdout.strip() == "", (
            f"Raw constructors found — must use factory methods:\n{result.stdout}"
        )
