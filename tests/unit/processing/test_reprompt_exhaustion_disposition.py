"""Tests that reprompt exhaustion produces EXHAUSTED disposition, not SUCCESS.

When reprompt exhausts max_attempts with persistent parse errors, the record
must be routed through ProcessingResult.exhausted() — not through the SUCCESS
transform path with an empty dict sentinel.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.processing.recovery.reprompt import RepromptResult
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingStatus,
    RecoveryMetadata,
    RepromptMetadata,
)


@pytest.fixture()
def basic_context():
    return ProcessingContext(
        agent_config={"name": "test_action", "intent": "test"},
        agent_name="test_action",
        record_index=0,
    )


@pytest.fixture()
def reprompt_exhausted_result():
    """Run process_record with a reprompt-exhausted invocation result."""
    from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy

    mock_invocation = MagicMock()
    mock_invocation.invoke.return_value = InvocationResult.immediate(
        response=None,
        executed=False,
        recovery=RecoveryMetadata(
            reprompt=RepromptMetadata(
                attempts=3,
                passed=False,
                validation="check_json",
                parse_error_count=3,
            )
        ),
    )

    agent_config = {"name": "test_action", "intent": "test"}
    strategy = OnlineLLMStrategy(agent_config, "test_action", invocation_strategy=mock_invocation)
    context = ProcessingContext(agent_config=agent_config, agent_name="test_action", record_index=0)

    with patch("agent_actions.processing.strategies.online_llm.get_task_preparer") as mock_tp:
        mock_prepared = MagicMock()
        mock_prepared.source_guid = "sg-1"
        mock_prepared.source_snapshot = None
        mock_prepared.original_content = {"field1": "val1"}
        mock_prepared.guard_status = None
        mock_tp.return_value.prepare.return_value = mock_prepared

        return strategy.process_record(
            {"content": {"field1": "val1"}, "source_guid": "sg-1"},
            context,
            skip_guard=False,
        )


class TestOnlineStrategyRepromptExhaustion:
    """Reprompt exhaustion must signal executed=False so online_llm routes to EXHAUSTED."""

    def test_reprompt_exhaustion_returns_not_executed(self, basic_context):
        """_invoke_with_reprompt returns executed=False when exhausted."""
        reprompt_service = MagicMock()
        reprompt_service.execute.return_value = RepromptResult(
            response=[{"_parse_error": "Failed to parse JSON"}],
            executed=True,
            attempts=3,
            passed=False,
            validation_name="check_json",
            exhausted=True,
            parse_error_count=3,
        )

        strategy = OnlineStrategy(reprompt_service=reprompt_service)
        task = MagicMock()
        task.should_execute = True
        task.is_passthrough = False
        task.passthrough_fields = {}
        task.formatted_prompt = "test"

        result = strategy.invoke(task, basic_context)

        assert result.response is None
        assert result.executed is False
        assert result.recovery_metadata is not None
        assert result.recovery_metadata.reprompt is not None
        assert result.recovery_metadata.reprompt.passed is False

    def test_reprompt_exhaustion_with_retry_returns_not_executed(self, basic_context):
        """_invoke_with_retry_and_reprompt returns executed=False when reprompt exhausted."""
        from agent_actions.processing.recovery.retry import RetryService

        retry_service = MagicMock(spec=RetryService)
        reprompt_service = MagicMock()
        reprompt_service.execute.return_value = RepromptResult(
            response=[{"_parse_error": "Failed to parse JSON"}],
            executed=True,
            attempts=2,
            passed=False,
            validation_name="check_json",
            exhausted=True,
            parse_error_count=2,
        )

        strategy = OnlineStrategy(retry_service=retry_service, reprompt_service=reprompt_service)
        task = MagicMock()
        task.should_execute = True
        task.is_passthrough = False
        task.passthrough_fields = {}
        task.formatted_prompt = "test"

        result = strategy.invoke(task, basic_context)

        assert result.response is None
        assert result.executed is False

    def test_successful_reprompt_still_returns_response(self, basic_context):
        """Non-exhausted reprompt returns the actual response normally."""
        reprompt_service = MagicMock()
        reprompt_service.execute.return_value = RepromptResult(
            response=[{"field": "value"}],
            executed=True,
            attempts=2,
            passed=True,
            validation_name="check_json",
            exhausted=False,
        )

        strategy = OnlineStrategy(reprompt_service=reprompt_service)
        task = MagicMock()
        task.should_execute = True
        task.is_passthrough = False
        task.passthrough_fields = {}
        task.formatted_prompt = "test"

        result = strategy.invoke(task, basic_context)

        assert result.response == [{"field": "value"}]
        assert result.executed is True


class TestProcessRecordRepromptExhaustion:
    """process_record must produce EXHAUSTED status for reprompt exhaustion."""

    def test_reprompt_exhaustion_produces_exhausted_tombstone(self, reprompt_exhausted_result):
        """When invocation returns executed=False with reprompt metadata, result is EXHAUSTED."""
        assert reprompt_exhausted_result.status == ProcessingStatus.EXHAUSTED
        assert reprompt_exhausted_result.data is not None
        assert len(reprompt_exhausted_result.data) == 1
        assert reprompt_exhausted_result.data[0].get("_tombstone") is True

    def test_reprompt_exhaustion_tombstone_reason_is_reprompt(self, reprompt_exhausted_result):
        """Tombstone must carry _tombstone_reason='reprompt_exhausted', not 'retry_exhausted'."""
        assert reprompt_exhausted_result.data[0]["_tombstone_reason"] == "reprompt_exhausted"


class TestExhaustedStateStampReason:
    """The EXHAUSTED lifecycle stamp must carry the tombstone's own reason."""

    def test_stamp_reason_follows_the_tombstone_reason(self):
        from agent_actions.processing.record_helpers import build_exhausted_tombstone
        from agent_actions.processing.result_collector import (
            collect_results_from_processing_results,
        )
        from agent_actions.processing.types import ProcessingResult

        tombstone = build_exhausted_tombstone(
            "test_action",
            {"content": {"field1": "v"}, "source_guid": "sg-1"},
            {"field1": None},
            source_guid="sg-1",
            reason="reprompt_exhausted",
        )
        result = ProcessingResult(
            status=ProcessingStatus.EXHAUSTED,
            data=[tombstone],
            source_guid="sg-1",
            error="Reprompt exhausted after 3 attempts",
        )
        output, _stats = collect_results_from_processing_results(
            [result], "test_action", agent_config={"name": "test_action"}
        )
        stamped = output[0]
        assert stamped["_state"] == "exhausted"
        assert stamped["_state_history"][-1]["reason"] == "reprompt_exhausted"
