"""Unit tests for InvocationStrategy pattern (Phase 3 #891)."""

import pytest
from unittest.mock import MagicMock, patch

from agent_actions.processing import (
    InvocationResult,
    InvocationStrategy,
    OnlineStrategy,
    BatchStrategy,
    BatchSubmissionResult,
    InvocationStrategyFactory,
    ProcessingMode,
)
from agent_actions.processing.prepared_task import GuardStatus, PreparedTask
from agent_actions.processing.types import ProcessingContext, RecoveryMetadata


@pytest.fixture
def basic_prepared_task():
    """Create a basic PreparedTask for testing."""
    return PreparedTask(
        target_id="test-id-123",
        source_guid="guid-456",
        formatted_prompt="Test prompt",
        llm_context={"content": "test content"},
        passthrough_fields={"pass": "through"},
        original_content={"original": "data"},
        guard_status=GuardStatus.PASSED,
    )


@pytest.fixture
def skipped_prepared_task():
    """Create a PreparedTask that was skipped by guard."""
    return PreparedTask(
        target_id="test-id-skip",
        source_guid="guid-skip",
        formatted_prompt="",
        original_content={"original": "skip-data"},
        guard_status=GuardStatus.SKIPPED,
        guard_behavior="skip",
        passthrough_fields={"pass": "skip"},
    )


@pytest.fixture
def filtered_prepared_task():
    """Create a PreparedTask that was filtered by guard."""
    return PreparedTask(
        target_id="test-id-filter",
        source_guid="guid-filter",
        formatted_prompt="",
        original_content={"original": "filter-data"},
        guard_status=GuardStatus.FILTERED,
        guard_behavior="filter",
    )


@pytest.fixture
def basic_context():
    """Create a basic ProcessingContext for testing."""
    return ProcessingContext(
        agent_config={"agent_type": "test_agent", "prompt": "test"},
        agent_name="test_agent",
        mode=ProcessingMode.ONLINE,
    )


class TestInvocationResult:
    """Tests for InvocationResult dataclass."""

    def test_immediate_factory(self):
        """Test InvocationResult.immediate() factory."""
        result = InvocationResult.immediate(
            response={"answer": "test"},
            executed=True,
            passthrough_fields={"pass": "through"},
        )

        assert result.response == {"answer": "test"}
        assert result.executed is True
        assert result.deferred is False
        assert result.passthrough_fields == {"pass": "through"}
        assert result.is_immediate is True
        assert result.is_success is True

    def test_queued_factory(self):
        """Test InvocationResult.queued() factory."""
        result = InvocationResult.queued(
            task_id="batch-task-123",
            passthrough_fields={"pass": "through"},
        )

        assert result.deferred is True
        assert result.task_id == "batch-task-123"
        assert result.executed is False
        assert result.response is None
        assert result.is_immediate is False

    def test_skipped_factory(self):
        """Test InvocationResult.skipped() factory."""
        result = InvocationResult.skipped(
            passthrough_data={"original": "data"},
            passthrough_fields={"pass": "through"},
        )

        assert result.response == {"original": "data"}
        assert result.executed is False
        assert result.deferred is False
        assert result.passthrough_fields == {"pass": "through"}

    def test_filtered_factory(self):
        """Test InvocationResult.filtered() factory."""
        result = InvocationResult.filtered()

        assert result.response is None
        assert result.executed is False
        assert result.deferred is False

    def test_is_success_requires_execution_and_response(self):
        """Test is_success property requires both executed=True and response."""
        # Not executed
        result1 = InvocationResult(response={"data": 1}, executed=False)
        assert result1.is_success is False

        # No response
        result2 = InvocationResult(response=None, executed=True)
        assert result2.is_success is False

        # Both present
        result3 = InvocationResult(response={"data": 1}, executed=True)
        assert result3.is_success is True


class TestOnlineStrategy:
    """Tests for OnlineStrategy."""

    def test_handles_skipped_task(self, skipped_prepared_task, basic_context):
        """Test OnlineStrategy returns skipped result for guard-skipped task."""
        strategy = OnlineStrategy()
        result = strategy.invoke(skipped_prepared_task, basic_context)

        assert result.executed is False
        assert result.response == {"original": "skip-data"}
        assert result.passthrough_fields == {"pass": "skip"}

    def test_handles_filtered_task(self, filtered_prepared_task, basic_context):
        """Test OnlineStrategy returns filtered result for guard-filtered task."""
        strategy = OnlineStrategy()
        result = strategy.invoke(filtered_prepared_task, basic_context)

        assert result.executed is False
        assert result.response is None

    @patch("agent_actions.processing.helpers.run_dynamic_agent")
    def test_direct_execution(self, mock_run_agent, basic_prepared_task, basic_context):
        """Test OnlineStrategy direct execution without recovery."""
        mock_run_agent.return_value = ({"answer": "42"}, True)

        strategy = OnlineStrategy()
        result = strategy.invoke(basic_prepared_task, basic_context)

        assert result.executed is True
        assert result.response == {"answer": "42"}
        assert result.recovery_metadata is None
        mock_run_agent.assert_called_once()

    def test_supports_recovery(self):
        """Test OnlineStrategy supports recovery."""
        strategy = OnlineStrategy()
        assert strategy.supports_recovery() is True

    @patch("agent_actions.processing.helpers.run_dynamic_agent")
    def test_retry_succeeds_after_failure(self, mock_run_agent, basic_prepared_task, basic_context):
        """Test retry service succeeds after initial failure — recovery metadata populated."""
        from agent_actions.processing.recovery.retry import RetryResult, RetryService

        mock_run_agent.return_value = ({"answer": "42"}, True)

        retry_service = MagicMock(spec=RetryService)
        retry_service.execute.return_value = RetryResult(
            response=({"answer": "42"}, True),
            attempts=2,
            reason="api_error",
            exhausted=False,
        )

        strategy = OnlineStrategy(retry_service=retry_service)
        result = strategy.invoke(basic_prepared_task, basic_context)

        assert result.executed is True
        assert result.response == {"answer": "42"}
        assert result.recovery_metadata is not None
        assert result.recovery_metadata.retry.attempts == 2
        assert result.recovery_metadata.retry.succeeded is True
        assert result.recovery_metadata.retry.reason == "api_error"

    @patch("agent_actions.processing.helpers.run_dynamic_agent")
    def test_retry_exhaustion_returns_not_executed(
        self, mock_run_agent, basic_prepared_task, basic_context
    ):
        """Test retry exhaustion returns executed=False with recovery metadata."""
        from agent_actions.processing.recovery.retry import RetryResult, RetryService

        retry_service = MagicMock(spec=RetryService)
        retry_service.execute.return_value = RetryResult(
            response=None,
            attempts=3,
            reason="timeout",
            exhausted=True,
            last_error="Request timed out",
        )

        strategy = OnlineStrategy(retry_service=retry_service)
        result = strategy.invoke(basic_prepared_task, basic_context)

        assert result.executed is False
        assert result.response is None
        assert result.recovery_metadata is not None
        assert result.recovery_metadata.retry.succeeded is False
        assert result.recovery_metadata.retry.attempts == 3

    @patch("agent_actions.processing.helpers.run_dynamic_agent")
    def test_reprompt_triggers_metadata(self, mock_run_agent, basic_prepared_task, basic_context):
        """Test reprompt service populates reprompt metadata when validation fails then passes."""
        from agent_actions.processing.recovery.reprompt import RepromptResult, RepromptService

        reprompt_service = MagicMock(spec=RepromptService)
        reprompt_service.execute.return_value = RepromptResult(
            response={"refined": "answer"},
            executed=True,
            attempts=2,
            passed=True,
            validation_name="check_json",
        )

        strategy = OnlineStrategy(reprompt_service=reprompt_service)
        result = strategy.invoke(basic_prepared_task, basic_context)

        assert result.executed is True
        assert result.response == {"refined": "answer"}
        assert result.recovery_metadata is not None
        assert result.recovery_metadata.reprompt.attempts == 2
        assert result.recovery_metadata.reprompt.passed is True
        assert result.recovery_metadata.reprompt.validation == "check_json"

    @patch("agent_actions.processing.helpers.run_dynamic_agent")
    def test_direct_execution_not_executed(
        self, mock_run_agent, basic_prepared_task, basic_context
    ):
        """Test direct execution with executed=False (LLM guard layer)."""
        mock_run_agent.return_value = (None, False)

        strategy = OnlineStrategy()
        result = strategy.invoke(basic_prepared_task, basic_context)

        assert result.executed is False
        assert result.response is None
        assert result.recovery_metadata is None


class TestBatchStrategy:
    """Tests for BatchStrategy."""

    def test_queues_task(self, basic_prepared_task, basic_context):
        """Test BatchStrategy queues tasks."""
        provider = MagicMock()
        strategy = BatchStrategy(provider)

        result = strategy.invoke(basic_prepared_task, basic_context)

        assert result.deferred is True
        assert result.task_id == "test-id-123"
        assert strategy.queued_count == 1

    def test_handles_skipped_task(self, skipped_prepared_task, basic_context):
        """Test BatchStrategy handles skipped tasks."""
        provider = MagicMock()
        strategy = BatchStrategy(provider)

        result = strategy.invoke(skipped_prepared_task, basic_context)

        assert result.deferred is False
        assert result.executed is False
        assert result.response == {"original": "skip-data"}
        assert strategy.queued_count == 0  # Not queued

    def test_handles_filtered_task(self, filtered_prepared_task, basic_context):
        """Test BatchStrategy handles filtered tasks."""
        provider = MagicMock()
        strategy = BatchStrategy(provider)

        result = strategy.invoke(filtered_prepared_task, basic_context)

        assert result.deferred is False
        assert result.executed is False
        assert result.response is None
        assert strategy.queued_count == 0

    def test_flush_submits_to_provider_and_returns_result(self, basic_prepared_task, basic_context):
        """Test flush() submits tasks to provider and returns BatchSubmissionResult with batch_id."""
        provider = MagicMock()
        provider.prepare_tasks.return_value = [{"formatted": "task"}]
        provider.submit_batch.return_value = ("batch-abc-123", "pending")

        strategy = BatchStrategy(provider)
        strategy.invoke(basic_prepared_task, basic_context)
        result = strategy.flush()

        # Provider was called with the prepared tasks
        provider.prepare_tasks.assert_called_once()
        provider.submit_batch.assert_called_once()

        # Result has the batch_id from the provider
        assert isinstance(result, BatchSubmissionResult)
        assert result.batch_id == "batch-abc-123"
        assert result.task_count == 1
        assert "test-id-123" in result.context_map
        assert strategy.queued_count == 0  # Cleared after flush

    def test_flush_empty_returns_empty_result(self):
        """Test flush() with no tasks returns empty result."""
        provider = MagicMock()
        strategy = BatchStrategy(provider)

        result = strategy.flush()

        assert result.is_empty is True
        assert result.task_count == 0

    def test_get_prepared_tasks(self, basic_prepared_task, basic_context):
        """Test get_prepared_tasks() returns task dicts."""
        provider = MagicMock()
        strategy = BatchStrategy(provider)

        strategy.invoke(basic_prepared_task, basic_context)
        tasks = strategy.get_prepared_tasks()

        assert len(tasks) == 1
        assert tasks[0]["target_id"] == "test-id-123"
        assert tasks[0]["prompt"] == "Test prompt"
        assert tasks[0]["content"] == {"content": "test content"}

    def test_supports_recovery(self):
        """Test BatchStrategy does not support inline recovery."""
        provider = MagicMock()
        strategy = BatchStrategy(provider)
        assert strategy.supports_recovery() is False

    def test_context_map_tracks_all_items(
        self, basic_prepared_task, skipped_prepared_task, basic_context
    ):
        """Test context_map tracks both included and skipped items."""
        provider = MagicMock()
        strategy = BatchStrategy(provider)

        strategy.invoke(basic_prepared_task, basic_context)
        strategy.invoke(skipped_prepared_task, basic_context)

        assert "test-id-123" in strategy.context_map
        assert "test-id-skip" in strategy.context_map
        assert strategy.context_map["test-id-123"]["status"] == "included"
        assert strategy.context_map["test-id-123"]["source_guid"] == "guid-456"
        assert strategy.context_map["test-id-skip"]["status"] == "skip"
        assert strategy.context_map["test-id-skip"]["source_guid"] == "guid-skip"

    def test_flush_clears_context_map_for_reuse(self, basic_prepared_task, basic_context):
        """Flush clears context_map so a reused instance doesn't leak stale IDs."""
        provider = MagicMock()
        provider.prepare_tasks.return_value = [{"formatted": "task"}]
        provider.submit_batch.return_value = ("batch-1", "pending")

        strategy = BatchStrategy(provider)

        # First batch
        strategy.invoke(basic_prepared_task, basic_context)
        result1 = strategy.flush()
        assert "test-id-123" in result1.context_map

        # After flush, internal state is clean
        assert strategy.context_map == {}
        assert strategy.queued_count == 0

        # Second batch with a different task should not contain first batch IDs
        second_task = PreparedTask(
            target_id="second-task-456",
            source_guid="guid-second",
            formatted_prompt="Second prompt",
            llm_context={"content": "second"},
            passthrough_fields={},
            original_content={"second": "data"},
            guard_status=GuardStatus.PASSED,
        )
        strategy.invoke(second_task, basic_context)
        result2 = strategy.flush()

        assert "second-task-456" in result2.context_map
        assert "test-id-123" not in result2.context_map


class TestInvocationStrategyFactory:
    """Tests for InvocationStrategyFactory."""

    def test_create_online_strategy(self):
        """Test factory creates OnlineStrategy for ONLINE mode."""
        strategy = InvocationStrategyFactory.create(
            mode=ProcessingMode.ONLINE,
            agent_config={"agent_type": "test"},
        )

        assert isinstance(strategy, OnlineStrategy)

    def test_create_batch_strategy(self):
        """Test factory creates BatchStrategy for BATCH mode."""
        provider = MagicMock()
        strategy = InvocationStrategyFactory.create(
            mode=ProcessingMode.BATCH,
            agent_config={"agent_type": "test"},
            provider=provider,
        )

        assert isinstance(strategy, BatchStrategy)

    def test_batch_mode_requires_provider(self):
        """Test BATCH mode raises error without provider."""
        with pytest.raises(ValueError, match="BatchProvider required"):
            InvocationStrategyFactory.create(
                mode=ProcessingMode.BATCH,
                agent_config={"agent_type": "test"},
            )

    def test_create_online_convenience(self):
        """Test create_online() convenience method."""
        strategy = InvocationStrategyFactory.create_online(
            agent_config={"agent_type": "test"},
        )

        assert isinstance(strategy, OnlineStrategy)

    def test_create_batch_convenience(self):
        """Test create_batch() convenience method."""
        provider = MagicMock()
        strategy = InvocationStrategyFactory.create_batch(provider)

        assert isinstance(strategy, BatchStrategy)


class TestRecordProcessorModeWiring:
    """Tests that RecordProcessor honors the mode parameter for strategy selection."""

    def test_default_mode_creates_online_strategy(self):
        """RecordProcessor with no mode/strategy defaults to OnlineStrategy."""
        from agent_actions.processing.processor import RecordProcessor

        processor = RecordProcessor(agent_config={}, agent_name="test")
        assert isinstance(processor._strategy, OnlineStrategy)

    def test_batch_mode_creates_batch_strategy(self):
        """RecordProcessor with mode=BATCH and provider creates BatchStrategy."""
        from agent_actions.processing.processor import RecordProcessor

        provider = MagicMock()
        processor = RecordProcessor(
            agent_config={},
            agent_name="test",
            mode=ProcessingMode.BATCH,
            provider=provider,
        )
        assert isinstance(processor._strategy, BatchStrategy)

    def test_batch_mode_without_provider_raises(self):
        """RecordProcessor with mode=BATCH but no provider raises ValueError."""
        from agent_actions.processing.processor import RecordProcessor

        with pytest.raises(ValueError, match="BatchProvider required"):
            RecordProcessor(
                agent_config={},
                agent_name="test",
                mode=ProcessingMode.BATCH,
            )

    def test_explicit_strategy_overrides_mode(self):
        """Explicit strategy parameter takes precedence over mode."""
        from agent_actions.processing.processor import RecordProcessor

        custom_strategy = MagicMock(spec=InvocationStrategy)
        processor = RecordProcessor(
            agent_config={},
            agent_name="test",
            strategy=custom_strategy,
            mode=ProcessingMode.BATCH,  # Should be ignored
        )
        assert processor._strategy is custom_strategy


class TestDeferredResultInProcessor:
    """Regression test: batch invocations must surface as DEFERRED, not FILTERED."""

    @patch("agent_actions.processing.processor.get_task_preparer")
    @patch("agent_actions.processing.processor.fire_event")
    def test_batch_invocation_returns_deferred_not_filtered(
        self, mock_fire_event, mock_get_preparer
    ):
        """
        When BatchStrategy.invoke() returns a deferred InvocationResult,
        RecordProcessor.process() must return ProcessingResult with
        status=DEFERRED and the task_id preserved — NOT status=FILTERED.

        Regression: Prior to this fix, deferred results (executed=False,
        response=None, deferred=True) fell through to the RP002 filter
        branch, discarding queued batch tasks.
        """
        from agent_actions.processing.processor import RecordProcessor
        from agent_actions.processing.types import (
            ProcessingContext,
            ProcessingMode,
            ProcessingStatus,
        )
        from agent_actions.processing.prepared_task import GuardStatus, PreparedTask

        # Set up a PreparedTask that passed guards
        prepared = PreparedTask(
            target_id="batch-task-789",
            source_guid="guid-batch-test",
            formatted_prompt="Test prompt",
            llm_context={"content": "test"},
            passthrough_fields={"key": "val"},
            original_content={"raw": "data"},
            guard_status=GuardStatus.PASSED,
            source_snapshot={"raw": "data"},
        )
        mock_preparer = MagicMock()
        mock_preparer.prepare.return_value = prepared
        mock_get_preparer.return_value = mock_preparer

        # Create a BatchStrategy that returns a deferred/queued result
        batch_strategy = MagicMock()
        batch_strategy.invoke.return_value = InvocationResult.queued(
            task_id="batch-task-789",
            passthrough_fields={"key": "val"},
        )

        processor = RecordProcessor(
            agent_config={"agent_type": "test"},
            agent_name="test",
            strategy=batch_strategy,
        )
        context = ProcessingContext(
            agent_config={"agent_type": "test"},
            agent_name="test",
            mode=ProcessingMode.BATCH,
        )

        result = processor.process({"raw": "data"}, context)

        # Must be DEFERRED, not FILTERED
        assert result.status == ProcessingStatus.DEFERRED
        assert result.task_id == "batch-task-789"
        assert result.node_id == "batch-task-789"  # underlying storage
        assert result.source_guid == "guid-batch-test"
        assert result.passthrough_fields == {"key": "val"}
        assert result.source_snapshot == {"raw": "data"}

        # RP002 (RecordFilteredEvent) must NOT have been fired
        filter_events = [
            call for call in mock_fire_event.call_args_list if hasattr(call[0][0], "filter_reason")
        ]
        assert len(filter_events) == 0, (
            f"RP002 RecordFilteredEvent should not fire for deferred results, "
            f"but got: {filter_events}"
        )


class TestProcessingResultTaskId:
    """Tests for ProcessingResult.task_id property."""

    def test_task_id_returns_value_for_deferred(self):
        """task_id returns the stored ID when status is DEFERRED."""
        from agent_actions.processing.types import ProcessingResult

        result = ProcessingResult.deferred(task_id="batch-123")
        assert result.task_id == "batch-123"

    def test_task_id_returns_none_for_non_deferred(self):
        """task_id returns None for SUCCESS, FILTERED, etc."""
        from agent_actions.processing.types import ProcessingResult

        assert ProcessingResult.success(data=[{}], node_id="node-1").task_id is None
        assert ProcessingResult.filtered(node_id="node-2").task_id is None
        assert ProcessingResult.failed(error="err", node_id="node-3").task_id is None


class TestBatchSubmissionResult:
    """Tests for BatchSubmissionResult dataclass."""

    def test_is_empty_when_no_tasks(self):
        """Test is_empty property when no tasks submitted."""
        result = BatchSubmissionResult(batch_id=None, task_count=0)
        assert result.is_empty is True

    def test_not_empty_when_has_tasks(self):
        """Test is_empty property when tasks submitted."""
        result = BatchSubmissionResult(batch_id="batch-123", task_count=5)
        assert result.is_empty is False
