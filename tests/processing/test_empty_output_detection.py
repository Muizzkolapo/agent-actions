"""Tests for empty output detection in the processing pipeline."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.schema import ActionConfig
from agent_actions.errors import EmptyOutputError
from agent_actions.logging.events.data_pipeline_events import RecordEmptyOutputEvent
from agent_actions.logging.events.handlers.run_results import ActionResult, RunResultsCollector
from agent_actions.processing.processor import _is_empty_output

# =============================================================================
# _is_empty_output helper tests
# =============================================================================


class TestIsEmptyOutput:
    """Tests for the _is_empty_output() helper function."""

    def test_none_is_empty(self):
        assert _is_empty_output(None) is True

    def test_empty_dict_is_empty(self):
        assert _is_empty_output({}) is True

    def test_empty_list_is_empty(self):
        assert _is_empty_output([]) is True

    def test_non_empty_dict_is_not_empty(self):
        assert _is_empty_output({"key": "val"}) is False

    def test_non_empty_list_is_not_empty(self):
        assert _is_empty_output([1, 2, 3]) is False

    def test_string_is_not_empty(self):
        assert _is_empty_output("hello") is False

    def test_empty_string_is_not_empty(self):
        """Empty string is not considered empty output (it's a valid response)."""
        assert _is_empty_output("") is False

    def test_zero_is_not_empty(self):
        assert _is_empty_output(0) is False

    def test_false_is_not_empty(self):
        assert _is_empty_output(False) is False


# =============================================================================
# RecordEmptyOutputEvent tests
# =============================================================================


class TestRecordEmptyOutputEvent:
    """Tests for the RecordEmptyOutputEvent event type."""

    def test_event_code(self):
        event = RecordEmptyOutputEvent(action_name="test_agent", record_index=0)
        assert event.code == "RP005"

    def test_event_level_is_warn(self):
        from agent_actions.logging.core.events import EventLevel

        event = RecordEmptyOutputEvent(action_name="test_agent", record_index=0)
        assert event.level == EventLevel.WARN

    def test_event_category(self):
        from agent_actions.logging.events.types import EventCategories

        event = RecordEmptyOutputEvent(action_name="test_agent", record_index=0)
        assert event.category == EventCategories.DATA_PROCESSING

    def test_event_message_contains_action_name(self):
        event = RecordEmptyOutputEvent(
            action_name="my_action",
            record_index=3,
            source_guid="guid-123",
            input_field_count=5,
        )
        assert "my_action" in event.message
        assert "Record 3" in event.message
        assert "guid-123" in event.message
        assert "5 fields" in event.message

    def test_event_data_dict(self):
        event = RecordEmptyOutputEvent(
            action_name="act",
            record_index=1,
            source_guid="sg",
            input_field_count=2,
            output={},
            on_empty="warn",
        )
        assert event.data["action_name"] == "act"
        assert event.data["record_index"] == 1
        assert event.data["source_guid"] == "sg"
        assert event.data["input_field_count"] == 2
        assert event.data["output"] == "{}"
        assert event.data["on_empty"] == "warn"


# =============================================================================
# ActionConfig on_empty field tests
# =============================================================================


class TestOnEmptyConfig:
    """Tests for the on_empty config field on ActionConfig."""

    def test_default_is_warn(self):
        config = ActionConfig(name="test", intent="test action")
        assert config.on_empty == "warn"

    def test_can_set_error(self):
        config = ActionConfig(name="test", intent="test action", on_empty="error")
        assert config.on_empty == "error"

    def test_can_set_skip(self):
        config = ActionConfig(name="test", intent="test action", on_empty="skip")
        assert config.on_empty == "skip"

    def test_invalid_value_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ActionConfig(name="test", intent="test action", on_empty="invalid")


# =============================================================================
# RecordProcessor empty output detection integration tests
# =============================================================================


class TestEmptyOutputDetection:
    """Tests for empty output detection in RecordProcessor.process()."""

    def test_empty_output_fires_warning_event(self):
        """When response is empty and on_empty=warn, a RecordEmptyOutputEvent fires."""
        fired_events = []

        with patch(
            "agent_actions.processing.record_processor.fire_event",
            side_effect=lambda e: fired_events.append(e),
        ):
            from agent_actions.processing.processor import RecordProcessor
            from agent_actions.processing.types import ProcessingContext

            # Build a minimal processor with a mock strategy returning empty response
            agent_config = {
                "name": "test_agent",
                "intent": "test",
                "on_empty": "warn",
            }

            mock_strategy = MagicMock()
            mock_result = MagicMock()
            mock_result.response = {}
            mock_result.executed = True
            mock_result.deferred = False
            mock_result.passthrough_fields = {}
            mock_result.recovery_metadata = None
            mock_result.task_id = None

            mock_strategy.invoke.return_value = mock_result

            processor = RecordProcessor(agent_config, "test_agent", strategy=mock_strategy)

            # Mock _transform_response to return a minimal valid result
            processor._transform_response = MagicMock(
                return_value=[{"content": {}, "source_guid": "sg-1"}]
            )

            context = ProcessingContext(
                agent_config=agent_config,
                agent_name="test_agent",
                record_index=0,
            )

            # Mock task_preparer
            with patch("agent_actions.processing.record_processor.get_task_preparer") as mock_tp:
                mock_prepared = MagicMock()
                mock_prepared.source_guid = "sg-1"
                mock_prepared.source_snapshot = None
                mock_prepared.original_content = {"field1": "val1"}
                mock_prepared.guard_status = None  # Not filtered
                mock_tp.return_value.prepare.return_value = mock_prepared

                processor.process({"content": {"field1": "val1"}, "source_guid": "sg-1"}, context)

        empty_events = [e for e in fired_events if isinstance(e, RecordEmptyOutputEvent)]
        assert len(empty_events) == 1
        assert empty_events[0].action_name == "test_agent"
        assert empty_events[0].on_empty == "warn"

    def test_empty_output_error_raises(self):
        """When on_empty=error, AgentActionsError is raised on empty output."""
        with patch(
            "agent_actions.processing.record_processor.fire_event",
        ):
            from agent_actions.processing.processor import RecordProcessor
            from agent_actions.processing.types import ProcessingContext

            agent_config = {
                "name": "test_agent",
                "intent": "test",
                "on_empty": "error",
            }

            mock_strategy = MagicMock()
            mock_result = MagicMock()
            mock_result.response = {}
            mock_result.executed = True
            mock_result.deferred = False
            mock_result.passthrough_fields = {}
            mock_result.recovery_metadata = None
            mock_result.task_id = None
            mock_strategy.invoke.return_value = mock_result

            processor = RecordProcessor(agent_config, "test_agent", strategy=mock_strategy)
            processor._transform_response = MagicMock(
                return_value=[{"content": {}, "source_guid": "sg-1"}]
            )

            context = ProcessingContext(
                agent_config=agent_config,
                agent_name="test_agent",
                record_index=0,
            )

            with patch("agent_actions.processing.record_processor.get_task_preparer") as mock_tp:
                mock_prepared = MagicMock()
                mock_prepared.source_guid = "sg-1"
                mock_prepared.source_snapshot = None
                mock_prepared.original_content = {"field1": "val1"}
                mock_prepared.guard_status = None
                mock_tp.return_value.prepare.return_value = mock_prepared

                with pytest.raises(EmptyOutputError, match="on_empty=error"):
                    processor.process(
                        {"content": {"field1": "val1"}, "source_guid": "sg-1"}, context
                    )

    def test_empty_output_skip_fires_event_for_observability(self):
        """When on_empty=skip, RecordEmptyOutputEvent still fires for observability."""
        fired_events = []

        with patch(
            "agent_actions.processing.record_processor.fire_event",
            side_effect=lambda e: fired_events.append(e),
        ):
            from agent_actions.processing.processor import RecordProcessor
            from agent_actions.processing.types import ProcessingContext

            agent_config = {
                "name": "test_agent",
                "intent": "test",
                "on_empty": "skip",
            }

            mock_strategy = MagicMock()
            mock_result = MagicMock()
            mock_result.response = {}
            mock_result.executed = True
            mock_result.deferred = False
            mock_result.passthrough_fields = {}
            mock_result.recovery_metadata = None
            mock_result.task_id = None
            mock_strategy.invoke.return_value = mock_result

            processor = RecordProcessor(agent_config, "test_agent", strategy=mock_strategy)
            processor._transform_response = MagicMock(
                return_value=[{"content": {}, "source_guid": "sg-1"}]
            )

            context = ProcessingContext(
                agent_config=agent_config,
                agent_name="test_agent",
                record_index=0,
            )

            with patch("agent_actions.processing.record_processor.get_task_preparer") as mock_tp:
                mock_prepared = MagicMock()
                mock_prepared.source_guid = "sg-1"
                mock_prepared.source_snapshot = None
                mock_prepared.original_content = {"field1": "val1"}
                mock_prepared.guard_status = None
                mock_tp.return_value.prepare.return_value = mock_prepared

                processor.process({"content": {"field1": "val1"}, "source_guid": "sg-1"}, context)

        empty_events = [e for e in fired_events if isinstance(e, RecordEmptyOutputEvent)]
        assert len(empty_events) == 1
        assert empty_events[0].on_empty == "skip"

    def test_empty_output_error_propagates_through_process_batch(self):
        """EmptyOutputError must propagate through process_batch (not be swallowed)."""
        with patch(
            "agent_actions.processing.record_processor.fire_event",
        ):
            from agent_actions.processing.processor import RecordProcessor
            from agent_actions.processing.types import ProcessingContext

            agent_config = {
                "name": "test_agent",
                "intent": "test",
                "on_empty": "error",
            }

            mock_strategy = MagicMock()
            mock_result = MagicMock()
            mock_result.response = {}
            mock_result.executed = True
            mock_result.deferred = False
            mock_result.passthrough_fields = {}
            mock_result.recovery_metadata = None
            mock_result.task_id = None
            mock_strategy.invoke.return_value = mock_result

            processor = RecordProcessor(agent_config, "test_agent", strategy=mock_strategy)
            processor._transform_response = MagicMock(
                return_value=[{"content": {}, "source_guid": "sg-1"}]
            )

            context = ProcessingContext(
                agent_config=agent_config,
                agent_name="test_agent",
                record_index=0,
            )

            with patch("agent_actions.processing.record_processor.get_task_preparer") as mock_tp:
                mock_prepared = MagicMock()
                mock_prepared.source_guid = "sg-1"
                mock_prepared.source_snapshot = None
                mock_prepared.original_content = {"field1": "val1"}
                mock_prepared.guard_status = None
                mock_tp.return_value.prepare.return_value = mock_prepared

                items = [{"content": {"field1": "val1"}, "source_guid": "sg-1"}]
                with pytest.raises(EmptyOutputError, match="on_empty=error"):
                    processor.process_batch(items, context)


# =============================================================================
# RunResultsCollector empty output tracking tests
# =============================================================================


class TestActionResultEmptyOutputTracking:
    """Tests for empty_output_records tracking in ActionResult and RunResultsCollector."""

    def test_action_result_default_zero(self):
        result = ActionResult(
            unique_id="wf.agent",
            action_name="agent",
            action_index=0,
            status="success",
        )
        assert result.empty_output_records == 0

    def test_action_result_in_to_dict(self):
        result = ActionResult(
            unique_id="wf.agent",
            action_name="agent",
            action_index=0,
            status="success",
            empty_output_records=3,
        )
        d = result.to_dict()
        assert d["empty_output_records"] == 3

    def test_collector_accepts_empty_output_event(self):
        collector = RunResultsCollector(workflow_name="test")
        event = RecordEmptyOutputEvent(action_name="agent1", record_index=0)
        assert collector.accepts(event) is True

    def test_collector_increments_empty_output_count(self):
        from agent_actions.logging.events.workflow_events import ActionCompleteEvent

        collector = RunResultsCollector(workflow_name="test")

        # Complete agent first so it exists in results
        complete_event = ActionCompleteEvent(action_name="agent1", action_index=0)
        collector.handle(complete_event)

        # Fire two empty output events
        event1 = RecordEmptyOutputEvent(action_name="agent1", record_index=0)
        collector.handle(event1)

        event2 = RecordEmptyOutputEvent(action_name="agent1", record_index=1)
        collector.handle(event2)

        assert collector._results["agent1"].empty_output_records == 2

    def test_collector_creates_entry_for_empty_output_before_complete(self):
        """Empty output event before AgentCompleteEvent should create entry and track count."""
        collector = RunResultsCollector(workflow_name="test")

        # Fire empty output BEFORE complete (real event ordering)
        event = RecordEmptyOutputEvent(action_name="agent1", record_index=0)
        collector.handle(event)

        assert "agent1" in collector._results
        assert collector._results["agent1"].empty_output_records == 1

    def test_collector_empty_output_count_survives_completion(self):
        """Empty output count set before complete should persist after AgentCompleteEvent."""
        from agent_actions.logging.events.workflow_events import ActionCompleteEvent

        collector = RunResultsCollector(workflow_name="test")

        # Empty output fires during processing (before complete)
        collector.handle(RecordEmptyOutputEvent(action_name="agent1", record_index=0))
        collector.handle(RecordEmptyOutputEvent(action_name="agent1", record_index=1))

        # Then agent completes — should update status but preserve empty count
        collector.handle(ActionCompleteEvent(action_name="agent1", action_index=0))

        result = collector._results["agent1"]
        assert result.status == "success"
        assert result.empty_output_records == 2
