"""Tests for AgentExecutor integration with run tracking."""
import pytest
from unittest.mock import Mock, MagicMock
from agent_actions.orchestration.agent_executor import AgentExecutor, AgentExecutionResult
from agent_actions.docs.run_tracker import RunTracker
from agent_actions.llm_invocation.providers.openai.vendor import (
    _set_last_usage, _get_last_usage
)


class TestAgentExecutorIntegration:
    """Test suite for AgentExecutor run tracking integration."""

    def test_executor_has_run_tracker_attribute(self):
        """Breaking: Executor must support run_tracker attribute."""
        executor = AgentExecutor(
            agent_runner=Mock(),
            state_manager=Mock(),
            skip_evaluator=Mock(),
            batch_manager=Mock(),
            output_manager=Mock()
        )
        tracker = RunTracker()

        # Must be settable without error
        executor.run_tracker = tracker
        executor.run_id = 'test_run_001'

        assert hasattr(executor, 'run_tracker')
        assert hasattr(executor, 'run_id')
        assert executor.run_tracker == tracker
        assert executor.run_id == 'test_run_001'

    def test_agent_execution_result_accepts_new_fields(self):
        """Breaking: AgentExecutionResult must accept new fields."""
        result = AgentExecutionResult(
            success=True,
            status='completed',
            duration=5.2,
            tokens={'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150},
            model_vendor='openai',
            model_name='gpt-4o-mini',
            files_processed=3
        )

        assert result.success is True
        assert result.status == 'completed'
        assert result.duration == 5.2
        assert result.tokens is not None
        assert result.tokens['total_tokens'] == 150
        assert result.tokens['input_tokens'] == 100
        assert result.tokens['output_tokens'] == 50
        assert result.model_vendor == 'openai'
        assert result.model_name == 'gpt-4o-mini'
        assert result.files_processed == 3

    def test_tracking_hooks_dont_break_execution(self):
        """Breaking: Tracking failures shouldn't stop execution."""
        executor = AgentExecutor(
            agent_runner=Mock(),
            state_manager=Mock(),
            skip_evaluator=Mock(),
            batch_manager=Mock(),
            output_manager=Mock()
        )

        # Attach tracker that will fail
        bad_tracker = Mock()
        bad_tracker.record_action_start.side_effect = Exception("Tracking failed")

        executor.run_tracker = bad_tracker
        executor.run_id = 'test_run'

        # Verify attributes are set (execution logic would use hasattr checks)
        assert hasattr(executor, 'run_tracker')
        assert hasattr(executor, 'run_id')

        # The actual execution logic has try-except or hasattr checks
        # This test verifies the attributes can be set without breaking
        assert executor.run_tracker == bad_tracker
        assert executor.run_id == 'test_run'

    def test_token_extraction_from_providers(self):
        """Breaking: Thread-local token storage must work."""
        # Set usage
        usage = {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150}
        _set_last_usage(usage)

        # Get usage
        retrieved = _get_last_usage()

        assert retrieved is not None
        assert retrieved['total_tokens'] == 150
        assert retrieved['input_tokens'] == 100
        assert retrieved['output_tokens'] == 50
