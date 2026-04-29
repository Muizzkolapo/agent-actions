"""Tests for source_guid=None → "" coercion in OnlineLLMStrategy.process_record().

When source_guid is None (e.g. non-first-stage item without source_guid key),
events must receive "" (not None) while ProcessingResult.source_guid stays None.
"""

from unittest.mock import MagicMock, patch

from agent_actions.logging.events.data_pipeline_events import (
    RecordProcessingStartedEvent,
    RecordTransformedEvent,
)
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingContext


def _make_strategy_and_context(agent_config=None):
    """Build a minimal OnlineLLMStrategy with mock invocation strategy for the success path."""
    agent_config = agent_config or {"name": "test_agent", "intent": "test"}

    mock_invocation = MagicMock()
    mock_result = MagicMock()
    mock_result.response = {"field": "value"}
    mock_result.executed = True
    mock_result.deferred = False
    mock_result.passthrough_fields = {}
    mock_result.recovery_metadata = None
    mock_result.task_id = None
    mock_invocation.invoke.return_value = mock_result

    strategy = OnlineLLMStrategy(agent_config, "test_agent", invocation_strategy=mock_invocation)
    strategy._transform_response = MagicMock(return_value=[{"content": {"field": "value"}}])

    context = ProcessingContext(
        agent_config=agent_config,
        agent_name="test_agent",
        record_index=0,
    )
    return strategy, context


class TestSourceGuidNoneCoercion:
    """source_guid=None must coerce to '' in events but stay None in ProcessingResult."""

    def test_events_receive_empty_string_when_source_guid_is_none(self):
        """All events emitted during process_record() get source_guid='' when prepared.source_guid is None."""
        fired_events = []
        collector = lambda e: fired_events.append(e)  # noqa: E731

        with patch(
            "agent_actions.processing.strategies.online_llm.fire_event",
            side_effect=collector,
        ):
            strategy, context = _make_strategy_and_context()

            with patch(
                "agent_actions.processing.strategies.online_llm.get_task_preparer"
            ) as mock_tp:
                mock_prepared = MagicMock()
                mock_prepared.source_guid = None  # The key scenario
                mock_prepared.source_snapshot = None
                mock_prepared.original_content = {"field": "value"}
                mock_prepared.guard_status = None
                mock_tp.return_value.prepare.return_value = mock_prepared

                result = strategy.process_record(
                    {"content": {"field": "value"}}, context, skip_guard=False
                )

        # Verify events received "" not None
        started = [e for e in fired_events if isinstance(e, RecordProcessingStartedEvent)]
        assert len(started) == 1
        assert started[0].source_guid == ""

        transformed = [e for e in fired_events if isinstance(e, RecordTransformedEvent)]
        assert len(transformed) == 1
        assert transformed[0].source_guid == ""

        # ProcessingResult preserves None
        assert result.source_guid is None

    def test_transform_response_receives_empty_string(self):
        """_transform_response is called with source_guid='' when prepared.source_guid is None."""
        with patch("agent_actions.processing.strategies.online_llm.fire_event"):
            strategy, context = _make_strategy_and_context()

            with patch(
                "agent_actions.processing.strategies.online_llm.get_task_preparer"
            ) as mock_tp:
                mock_prepared = MagicMock()
                mock_prepared.source_guid = None
                mock_prepared.source_snapshot = None
                mock_prepared.original_content = {"field": "value"}
                mock_prepared.guard_status = None
                mock_tp.return_value.prepare.return_value = mock_prepared

                strategy.process_record({"content": {"field": "value"}}, context, skip_guard=False)

        # _transform_response should have been called with "" as source_guid
        call_args = strategy._transform_response.call_args
        assert call_args[0][2] == ""  # 3rd positional arg is source_guid

    def test_processing_result_preserves_none_source_guid(self):
        """ProcessingResult.source_guid stays None — not coerced to ''."""
        with patch("agent_actions.processing.strategies.online_llm.fire_event"):
            strategy, context = _make_strategy_and_context()

            with patch(
                "agent_actions.processing.strategies.online_llm.get_task_preparer"
            ) as mock_tp:
                mock_prepared = MagicMock()
                mock_prepared.source_guid = None
                mock_prepared.source_snapshot = None
                mock_prepared.original_content = {"field": "value"}
                mock_prepared.guard_status = None
                mock_tp.return_value.prepare.return_value = mock_prepared

                result = strategy.process_record(
                    {"content": {"field": "value"}}, context, skip_guard=False
                )

        assert result.source_guid is None
        assert result.status.value == "success"
