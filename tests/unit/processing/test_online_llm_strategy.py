"""Tests for OnlineLLMStrategy — the online LLM processing strategy."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.processing.prepared_task import GuardStatus, PreparedTask
from agent_actions.processing.strategies.online_llm import (
    OnlineLLMStrategy,
    _create_item_context,
)
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)
from agent_actions.processing.unified import ProcessingStrategy
from agent_actions.record.reasons import EMPTY_OUTPUT
from agent_actions.record.state import RecordState


def _make_context(
    agent_name: str = "test_action",
    **kwargs: Any,
) -> ProcessingContext:
    """Create a minimal ProcessingContext."""
    config: dict[str, Any] = {
        "agent_type": agent_name,
        "name": agent_name,
    }
    return ProcessingContext(
        agent_config=config,
        agent_name=agent_name,
        **kwargs,
    )


def _make_prepared(
    source_guid: str = "sg-1",
    guard_status: GuardStatus = GuardStatus.PASSED,
    **kwargs: Any,
) -> PreparedTask:
    """Create a minimal PreparedTask."""
    return PreparedTask(
        target_id="tid-1",
        source_guid=source_guid,
        formatted_prompt="test prompt",
        llm_context={"content": "test"},
        original_content={"field": "value"},
        source_snapshot={"field": "value"},
        guard_status=guard_status,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


class TestProtocolCompliance:
    """OnlineLLMStrategy must satisfy ProcessingStrategy protocol."""

    def test_satisfies_processing_strategy_protocol(self):
        mock_invocation = MagicMock()
        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )
        assert isinstance(strategy, ProcessingStrategy)


# ---------------------------------------------------------------------------
# process_record — happy path
# ---------------------------------------------------------------------------


class TestProcessRecordSuccess:
    """Tests for successful record processing."""

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_success_returns_correct_status(self, mock_fire, mock_get_preparer):
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response={"output": "result"},
            executed=True,
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )
        strategy._transform_response = MagicMock(
            return_value=[{"content": {"test": {"output": "result"}}}]
        )

        context = _make_context()
        result = strategy.process_record({"field": "value"}, context)

        assert result.status == ProcessingStatus.SUCCESS
        assert result.source_guid == "sg-1"

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_skip_guard_defaults_to_false(self, mock_fire, mock_get_preparer):
        """process_record defaults to skip_guard=False — per-record guard evaluates."""
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response={"out": "val"}, executed=True
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )
        strategy._transform_response = MagicMock(return_value=[{"content": {}}])

        context = _make_context()
        strategy.process_record({"field": "value"}, context)

        # TaskPreparer.prepare() should receive skip_guard=False (per-record guard evaluates)
        call_kwargs = mock_get_preparer.return_value.prepare.call_args
        assert call_kwargs[1]["skip_guard"] is False


# ---------------------------------------------------------------------------
# process_record — guard statuses
# ---------------------------------------------------------------------------


class TestProcessRecordGuardStatuses:
    """Tests for guard status handling in process_record."""

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_upstream_unprocessed_returns_unprocessed(self, mock_fire, mock_get_preparer):
        prepared = _make_prepared(guard_status=GuardStatus.UPSTREAM_UNPROCESSED)
        mock_get_preparer.return_value.prepare.return_value = prepared

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )

        item = {"content": {"field": "value"}, "_unprocessed": True, "metadata": {}}
        context = _make_context()
        result = strategy.process_record(item, context)

        assert result.status == ProcessingStatus.UNPROCESSED
        assert result.skip_reason == "upstream_unprocessed"

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_filtered_guard_returns_filtered(self, mock_fire, mock_get_preparer):
        """When skip_guard=False and guard filters, returns FILTERED."""
        prepared = _make_prepared(guard_status=GuardStatus.FILTERED)
        mock_get_preparer.return_value.prepare.return_value = prepared

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )

        context = _make_context()
        result = strategy.process_record({"field": "value"}, context, skip_guard=False)

        assert result.status == ProcessingStatus.FILTERED

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_skipped_guard_returns_skipped(self, mock_fire, mock_get_preparer):
        """When skip_guard=False and guard skips, returns SKIPPED."""
        prepared = _make_prepared(
            guard_status=GuardStatus.SKIPPED,
            guard_behavior="skip",
        )
        mock_get_preparer.return_value.prepare.return_value = prepared

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )

        context = _make_context()
        result = strategy.process_record({"field": "value"}, context, skip_guard=False)

        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "guard_skip"


# ---------------------------------------------------------------------------
# process_record — LLM response handling
# ---------------------------------------------------------------------------


class TestProcessRecordResponseHandling:
    """Tests for LLM response handling in process_record."""

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_deferred_returns_deferred(self, mock_fire, mock_get_preparer):
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.queued(
            task_id="batch-123",
            passthrough_fields={"k": "v"},
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        context = _make_context()
        result = strategy.process_record({"field": "value"}, context)

        assert result.status == ProcessingStatus.DEFERRED
        assert result.task_id == "batch-123"

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_not_executed_none_response_returns_filtered(self, mock_fire, mock_get_preparer):
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response=None, executed=False
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        context = _make_context()
        result = strategy.process_record({"field": "value"}, context)

        assert result.status == ProcessingStatus.FILTERED

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_retry_exhausted_returns_exhausted(self, mock_fire, mock_get_preparer):
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        recovery = RecoveryMetadata(
            retry=RetryMetadata(attempts=3, failures=3, succeeded=False, reason="timeout")
        )
        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response=None,
            executed=False,
            recovery=recovery,
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        context = _make_context()
        result = strategy.process_record({"field": "value"}, context)

        assert result.status == ProcessingStatus.EXHAUSTED
        assert "3 attempts" in result.error

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_expectations_exhausted_returns_tombstone_with_reason(
        self, mock_fire, mock_get_preparer
    ):
        from agent_actions.processing.types import ExpectationsMetadata

        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        recovery = RecoveryMetadata(
            expectations=ExpectationsMetadata(attempts=3, failed=["count", "_structural"])
        )
        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response=None,
            executed=False,
            recovery=recovery,
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        result = strategy.process_record({"field": "value"}, _make_context())

        assert result.status == ProcessingStatus.EXHAUSTED
        assert "3 iteration" in result.error
        tombstone = result.data[0]
        assert tombstone["_tombstone"] is True
        assert tombstone["_tombstone_reason"] == "expectations_exhausted"
        assert tombstone["metadata"]["expectations_failed"] == ["count", "_structural"]
        assert tombstone["metadata"]["expectations_iterations"] == 3

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_not_executed_with_response_returns_skipped(self, mock_fire, mock_get_preparer):
        """executed=False with non-None response → guard_skip → SKIPPED."""
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response={"skipped": True}, executed=False
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        context = _make_context()
        result = strategy.process_record({"field": "value"}, context)

        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == "guard_skip"


# ---------------------------------------------------------------------------
# process_record — empty output
# ---------------------------------------------------------------------------


class TestProcessRecordEmptyOutput:
    """Tests for empty output handling."""

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_empty_output_error_raises(self, mock_fire, mock_get_preparer):
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(response={}, executed=True)

        from agent_actions.errors.processing import EmptyOutputError

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test", "on_empty": "error"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        context = _make_context()
        context = ProcessingContext(
            agent_config={"agent_type": "test", "on_empty": "error"},
            agent_name="test",
        )

        with pytest.raises(EmptyOutputError, match="on_empty=error"):
            strategy.process_record({"field": "value"}, context)

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_empty_output_warn_returns_failed(self, mock_fire, mock_get_preparer):
        """on_empty=warn must return FAILED, not SUCCESS with empty data (F10 regression)."""
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(response={}, executed=True)

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test", "on_empty": "warn"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        context = ProcessingContext(
            agent_config={"agent_type": "test", "on_empty": "warn"},
            agent_name="test",
        )

        result = strategy.process_record({"field": "value"}, context)

        assert result.status == ProcessingStatus.FAILED
        assert "Empty LLM response" in result.error

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_empty_output_warn_default_returns_failed(self, mock_fire, mock_get_preparer):
        """Default on_empty (warn) must return FAILED for empty responses (F10 regression)."""
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response=None, executed=True
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        context = ProcessingContext(
            agent_config={"agent_type": "test"},
            agent_name="test",
        )

        result = strategy.process_record({"field": "value"}, context)

        assert result.status == ProcessingStatus.FAILED
        assert "Empty LLM response" in result.error

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_empty_output_skip_returns_skipped(self, mock_fire, mock_get_preparer):
        """on_empty=skip must return SKIPPED with tombstone, not SUCCESS with empty data."""
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(response=[], executed=True)

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test", "on_empty": "skip"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        context = ProcessingContext(
            agent_config={"agent_type": "test", "on_empty": "skip"},
            agent_name="test",
        )

        result = strategy.process_record({"field": "value"}, context)

        assert result.status == ProcessingStatus.SKIPPED
        assert result.skip_reason == EMPTY_OUTPUT
        assert len(result.data) == 1  # tombstone record

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_nonempty_output_still_succeeds(self, mock_fire, mock_get_preparer):
        """Non-empty LLM responses must still produce SUCCESS (F10 guard)."""
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response={"result": "data"}, executed=True
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test", "on_empty": "warn"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )

        context = ProcessingContext(
            agent_config={"agent_type": "test", "on_empty": "warn"},
            agent_name="test",
        )

        result = strategy.process_record({"field": "value"}, context)

        assert result.status == ProcessingStatus.SUCCESS
        assert len(result.data) > 0


# ---------------------------------------------------------------------------
# invoke — batch loop
# ---------------------------------------------------------------------------


class TestInvokeBatchLoop:
    """Tests for the batch iteration in invoke()."""

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_processes_all_records(self, mock_fire, mock_get_preparer):
        prepared = _make_prepared()
        mock_get_preparer.return_value.prepare.return_value = prepared

        mock_invocation = MagicMock()
        mock_invocation.invoke.return_value = InvocationResult.immediate(
            response={"out": "val"}, executed=True
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=mock_invocation,
        )
        strategy._transform_response = MagicMock(return_value=[{"content": {}}])

        records = [{"f": "1"}, {"f": "2"}, {"f": "3"}]
        context = _make_context()
        results = strategy.invoke(records, context)

        assert len(results) == 3
        assert all(r.status == ProcessingStatus.SUCCESS for r in results)

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_wraps_generic_exception_as_failed(self, mock_fire, mock_get_preparer):
        """Non-critical exceptions are wrapped as FAILED results."""
        mock_get_preparer.return_value.prepare.side_effect = ValueError("boom")

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )

        context = _make_context()
        results = strategy.invoke([{"f": "1"}], context)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert "boom" in results[0].error

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_first_stage_exception_keeps_stamped_source_guid(self, mock_fire, mock_get_preparer):
        """A first-stage record hitting the generic-exception path must carry its STAMPED
        source_guid (the persisted source_data key), not a value re-derived over the
        already-stamped item — else the FAILED disposition is keyed on a guid absent from
        source_data and cross-run failure matching breaks."""
        from agent_actions.utils.id_generation import IDGenerator

        mock_get_preparer.return_value.prepare.side_effect = ValueError("boom")
        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )
        # A first-stage record stamped upstream (unified.py), the way ingestion persisted it.
        raw = {"content": "x", "question": "q"}
        stamped_guid = IDGenerator.derive_source_guid(raw)
        record = {**raw, "source_guid": stamped_guid}
        # Re-deriving over the stamped record DIVERGES (the guid is now in the hash), so a
        # test asserting "some guid" would miss the bug — pin the exact stamped value.
        assert IDGenerator.derive_source_guid(record) != stamped_guid

        results = strategy.invoke([record], _make_context(is_first_stage=True))

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert results[0].source_guid == stamped_guid

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_reraises_configuration_error(self, mock_fire, mock_get_preparer):
        from agent_actions.errors import ConfigurationError

        mock_get_preparer.return_value.prepare.side_effect = ConfigurationError("bad config")

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )

        context = _make_context()
        with pytest.raises(ConfigurationError, match="bad config"):
            strategy.invoke([{"f": "1"}], context)

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_template_variable_error_with_missing_vars_produces_tombstone(
        self, mock_fire, mock_get_preparer
    ):
        """TemplateVariableError with non-empty missing_variables is per-record — tombstone."""
        from jinja2 import UndefinedError

        from agent_actions.errors.operations import TemplateVariableError

        mock_get_preparer.return_value.prepare.side_effect = TemplateVariableError(
            missing_variables=["page_content"],
            available_variables=["source"],
            agent_name="test",
            mode="online",
            cause=UndefinedError("'page_content' is undefined"),
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )

        context = _make_context()
        results = strategy.invoke([{"f": "1"}], context)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert results[0].data[0]["_state"] == RecordState.FAILED.value

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_template_syntax_error_still_reraises(self, mock_fire, mock_get_preparer):
        """TemplateVariableError with empty missing_variables (syntax error) is action-fatal."""
        from agent_actions.errors.operations import TemplateVariableError

        mock_get_preparer.return_value.prepare.side_effect = TemplateVariableError(
            missing_variables=[],
            available_variables=["source"],
            agent_name="test",
            mode="online",
            cause=Exception("invalid syntax"),
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )

        context = _make_context()
        with pytest.raises(TemplateVariableError):
            strategy.invoke([{"f": "1"}], context)

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_record_context_error_produces_tombstone(self, mock_fire, mock_get_preparer):
        """RecordContextError is per-record — tombstone, remaining records continue."""
        from agent_actions.errors import RecordContextError

        mock_get_preparer.return_value.prepare.side_effect = RecordContextError(
            "declared fields ['question'] not found"
        )

        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )

        context = _make_context()
        results = strategy.invoke([{"f": "1"}], context)

        assert len(results) == 1
        assert results[0].status == ProcessingStatus.FAILED
        assert results[0].data[0]["_state"] == RecordState.FAILED.value

    @patch("agent_actions.processing.strategies.online_llm.get_task_preparer")
    @patch("agent_actions.processing.strategies.online_llm.fire_event")
    def test_empty_records_returns_empty(self, mock_fire, mock_get_preparer):
        strategy = OnlineLLMStrategy(
            agent_config={"agent_type": "test"},
            agent_name="test",
            invocation_strategy=MagicMock(),
        )

        context = _make_context()
        results = strategy.invoke([], context)

        assert results == []


# ---------------------------------------------------------------------------
# _create_item_context helper
# ---------------------------------------------------------------------------


class TestCreateItemContext:
    """Tests for _create_item_context helper."""

    def test_updates_record_index(self):
        base = _make_context()
        ctx = _create_item_context(base, 5, {"data": "val"})
        assert ctx.record_index == 5

    def test_sets_current_item_for_dict(self):
        base = _make_context()
        item = {"data": "val"}
        ctx = _create_item_context(base, 0, item)
        assert ctx.current_item is item

    def test_sets_current_item_none_for_non_dict(self):
        base = _make_context()
        ctx = _create_item_context(base, 0, "string_item")
        assert ctx.current_item is None
