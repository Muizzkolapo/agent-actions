"""End-to-end tests for record fate on prompt template/context failures.

Verifies the complete chain: prep failure → tombstone → cascade detection →
downstream UPSTREAM_UNPROCESSED, across both online and batch paths.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.errors import RecordContextError
from agent_actions.errors.operations import TemplateVariableError
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.record.state import RecordState


def _make_context(**kwargs: Any) -> ProcessingContext:
    config: dict[str, Any] = {"agent_type": "test_action", "name": "test_action"}
    return ProcessingContext(
        agent_config=config,
        agent_name="test_action",
        **kwargs,
    )


class TestOnlineMultiRecordContinuation:
    """One record fails prep, remaining records continue processing."""

    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_first_record_fails_others_succeed(self, _mock_fire):
        """3 records: record 0 fails via TemplateVariableError, records 1-2 succeed."""
        from jinja2 import UndefinedError

        error = TemplateVariableError(
            missing_variables=["question"],
            available_variables=["source"],
            agent_name="test_action",
            mode="online",
            cause=UndefinedError("'question' is undefined"),
        )
        success_result = ProcessingResult.success(
            data=[{"content": {"test_action": {"answer": "yes"}}}],
            source_guid="sg_success",
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test_action"},
            agent_name="test_action",
            invocation_strategy=MagicMock(),
        )
        # Mock process_record: first call raises, rest succeed
        strategy.process_record = MagicMock(
            side_effect=[error, success_result, success_result]
        )

        context = _make_context()
        records = [
            {"source_guid": "sg_fail", "content": {}},
            {"source_guid": "sg_ok1", "content": {}},
            {"source_guid": "sg_ok2", "content": {}},
        ]
        results = strategy.invoke(records, context)

        assert len(results) == 3
        # Record 0: tombstone
        assert results[0].status == ProcessingStatus.UNPROCESSED
        assert results[0].data[0]["_state"] == RecordState.FAILED.value
        # Records 1-2: success
        assert results[1].status == ProcessingStatus.SUCCESS
        assert results[2].status == ProcessingStatus.SUCCESS

    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_record_context_error_others_continue(self, _mock_fire):
        """RecordContextError on one record doesn't block others."""
        success_result = ProcessingResult.success(
            data=[{"content": {"test_action": {"ok": True}}}],
            source_guid="sg_ok",
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test_action"},
            agent_name="test_action",
            invocation_strategy=MagicMock(),
        )
        strategy.process_record = MagicMock(
            side_effect=[
                RecordContextError("declared fields ['options'] not found"),
                success_result,
            ]
        )

        context = _make_context()
        results = strategy.invoke(
            [{"source_guid": "sg_fail"}, {"source_guid": "sg_ok"}], context
        )

        assert len(results) == 2
        assert results[0].status == ProcessingStatus.UNPROCESSED
        assert results[1].status == ProcessingStatus.SUCCESS


class TestCascadePropagation:
    """Prep-failed tombstone cascades to downstream action via _state detection."""

    def test_failed_record_detected_as_upstream_unprocessed(self):
        """TaskPreparer.prepare() returns UPSTREAM_UNPROCESSED for _state=failed record."""
        # Build a tombstone like _build_prep_failed_result produces
        from agent_actions.processing.record_helpers import build_tombstone
        from agent_actions.record.envelope import RecordEnvelope
        from agent_actions.record.reasons import PREP_FAILED

        tombstone = build_tombstone(
            action_name="action_a",
            input_record={"source_guid": "sg_001", "content": {}},
            reason=PREP_FAILED,
            source_guid="sg_001",
        )
        RecordEnvelope.transition(
            tombstone, RecordState.FAILED, "action_a", "missing field"
        )

        # Downstream action sees this tombstone
        preparer = TaskPreparer()
        downstream_ctx = PreparationContext(
            agent_config={
                "agent_type": "action_b",
                "context_scope": {"observe": ["action_a.*"]},
            },
            agent_name="action_b",
            is_first_stage=False,
        )
        result = preparer.prepare(tombstone, downstream_ctx)
        assert result.guard_status == GuardStatus.UPSTREAM_UNPROCESSED

    def test_failed_state_history_preserved_through_cascade(self):
        """Original failure reason is preserved in _state_history after cascade."""
        from agent_actions.processing.record_helpers import build_tombstone
        from agent_actions.record.envelope import RecordEnvelope
        from agent_actions.record.reasons import PREP_FAILED

        tombstone = build_tombstone(
            action_name="action_a",
            input_record={"source_guid": "sg_001", "content": {}},
            reason=PREP_FAILED,
            source_guid="sg_001",
        )
        RecordEnvelope.transition(
            tombstone, RecordState.FAILED, "action_a", "Template var 'question' missing"
        )

        assert tombstone["_state"] == RecordState.FAILED.value
        assert len(tombstone["_state_history"]) == 1
        assert "question" in tombstone["_state_history"][0]["reason"]


class TestResultCollectorPrepFailedDisposition:
    """ResultCollector counts prep-failed tombstones correctly."""

    def test_unprocessed_result_counted_separately(self):
        """Prep-failed results (UNPROCESSED) don't inflate success or failure counts."""
        from agent_actions.record.reasons import PREP_FAILED

        mock_backend = MagicMock()

        results = [
            ProcessingResult.success(
                data=[{"content": {"test_action": {"ok": True}}, "source_guid": "sg_1"}],
                source_guid="sg_1",
            ),
            ProcessingResult.unprocessed(
                data=[{
                    "content": {"test_action": None},
                    "_state": RecordState.FAILED.value,
                    "source_guid": "sg_2",
                }],
                reason=PREP_FAILED,
                source_guid="sg_2",
            ),
        ]

        output, stats = ResultCollector.collect_results(
            results,
            agent_config={"agent_type": "test_action"},
            agent_name="test_action",
            is_first_stage=False,
            storage_backend=mock_backend,
        )
        assert stats.success > 0
        assert stats.unprocessed > 0
