"""Tests for ResultCollector and ExhaustedRecordBuilder."""

from typing import Any, Dict

import pytest

from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.result_collector import ResultCollector
from agent_actions.processing.types import (
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)
from agent_actions.errors import AgentActionsException
from agent_actions.utils.id_generation import IDGenerator


def _retry_metadata() -> RecoveryMetadata:
    return RecoveryMetadata(
        retry=RetryMetadata(
            attempts=2,
            failures=2,
            succeeded=False,
            reason="timeout",
        )
    )


def test_result_collector_aggregates_statuses_first_stage():
    """ResultCollector now expects EXHAUSTED results to arrive with pre-populated data."""
    agent_config = {
        "agent_type": "test_action",
        "schema": {
            "properties": {
                "field": {"type": "string"},
                "flag": {"type": "boolean"},
                "count": {"type": "integer"},
                "items": {"type": "array"},
                "obj": {"type": "object"},
            }
        },
    }

    success = ProcessingResult.success(data=[{"content": {"value": 1}}], source_guid="src-1")
    skipped = ProcessingResult.skipped(
        passthrough_data={"content": {"value": 2}}, reason="guard_skip", source_guid="src-2"
    )

    # EXHAUSTED results now arrive pre-enriched from processor.py
    exhausted_data = {
        "source_guid": "src-3",
        "target_id": "t-1",
        "lineage": ["prev", "action_node"],
        "node_id": "action_node",
        "metadata": {"retry_exhausted": True},
        "_recovery": {
            "retry": {"attempts": 2, "failures": 2, "succeeded": False, "reason": "timeout"}
        },
        "content": {
            "field": None,
            "flag": False,
            "count": 0,
            "items": [],
            "obj": {},
        },
    }
    exhausted = ProcessingResult.exhausted(
        error="Retry exhausted",
        source_guid="src-3",
        recovery_metadata=_retry_metadata(),
    )
    exhausted.data = [exhausted_data]

    failed = ProcessingResult.failed(error="Boom", source_guid="src-4")
    filtered = ProcessingResult.filtered(source_guid="src-5")

    output = ResultCollector.collect_results(
        [success, skipped, exhausted, failed, filtered],
        agent_config,
        "fallback_name",
        is_first_stage=True,
    )

    assert output[0] == {"content": {"value": 1}}
    assert output[1] == {"content": {"value": 2}}

    exhausted_item = output[2]
    assert exhausted_item["source_guid"] == "src-3"
    assert exhausted_item["target_id"] == "t-1"
    assert exhausted_item["lineage"] == ["prev", "action_node"]
    assert exhausted_item["metadata"]["retry_exhausted"] is True
    assert exhausted_item["_recovery"]["retry"]["attempts"] == 2
    assert exhausted_item["content"] == {
        "field": None,
        "flag": False,
        "count": 0,
        "items": [],
        "obj": {},
    }
    assert len(output) == 3


def test_result_collector_uses_input_record_downstream():
    """Downstream stages: EXHAUSTED results arrive pre-enriched with correct lineage."""
    agent_config = {"agent_type": "downstream"}

    # Pre-enriched exhausted data (as processor.py would produce)
    exhausted_data = {
        "source_guid": "src-9",
        "target_id": "t-input",
        "lineage": ["input", "action_node"],
        "node_id": "action_node",
        "metadata": {"retry_exhausted": True},
        "_recovery": {
            "retry": {"attempts": 2, "failures": 2, "succeeded": False, "reason": "timeout"}
        },
        "content": {},
    }
    exhausted = ProcessingResult.exhausted(
        error="Retry exhausted",
        source_guid="src-9",
        recovery_metadata=_retry_metadata(),
    )
    exhausted.data = [exhausted_data]

    output = ResultCollector.collect_results(
        [exhausted],
        agent_config,
        "downstream",
        is_first_stage=False,
    )

    exhausted_item = output[0]
    assert exhausted_item["target_id"] == "t-input"
    assert exhausted_item["lineage"] == ["input", "action_node"]


def test_result_collector_handles_none_data():
    result = ProcessingResult(status=ProcessingStatus.SUCCESS, data=None)  # type: ignore[arg-type]

    output = ResultCollector.collect_results(
        [result],
        agent_config={},
        agent_name="test",
        is_first_stage=True,
    )

    assert output == []


def test_exhausted_record_builder_preserves_lineage(monkeypatch):
    monkeypatch.setattr(IDGenerator, "generate_node_id", lambda _: "action_node")
    agent_config: Dict[str, Any] = {"agent_type": "builder_action"}
    original_row = {"lineage": ["root"], "target_id": "t-7"}

    exhausted_item = ExhaustedRecordBuilder.build_exhausted_item(
        source_guid="src-7",
        original_row=original_row,
        recovery_metadata=_retry_metadata(),
        agent_config=agent_config,
        action_name="builder_action",
    )

    assert exhausted_item["target_id"] == "t-7"
    assert exhausted_item["lineage"] == ["root", "action_node"]


def test_exhausted_record_builder_build_empty_content():
    """Test that build_empty_content produces correct type-appropriate defaults."""
    agent_config = {
        "schema": {
            "properties": {
                "name": {"type": "string"},
                "active": {"type": "boolean"},
                "count": {"type": "integer"},
                "score": {"type": "number"},
                "tags": {"type": "array"},
                "meta": {"type": "object"},
            }
        }
    }
    empty = ExhaustedRecordBuilder.build_empty_content(agent_config)
    assert empty == {
        "name": None,
        "active": False,
        "count": 0,
        "score": 0,
        "tags": [],
        "meta": {},
    }

    # No schema returns empty dict
    assert ExhaustedRecordBuilder.build_empty_content({}) == {}


def test_result_collector_on_exhausted_raise():
    """Test that on_exhausted=raise throws AgentActionsException."""
    agent_config = {
        "agent_type": "test_action",
        "retry": {"on_exhausted": "raise"},
    }
    exhausted = ProcessingResult.exhausted(
        error="Retry exhausted",
        source_guid="src-raise",
        recovery_metadata=_retry_metadata(),
        input_record={"target_id": "t-1"},
    )

    with pytest.raises(AgentActionsException) as exc_info:
        ResultCollector.collect_results(
            [exhausted],
            agent_config,
            "test_agent",
            is_first_stage=True,
        )

    assert "on_exhausted=raise" in str(exc_info.value)
    assert exc_info.value.context["exhausted_records"] == 1


def test_result_collector_on_exhausted_return_last_does_not_raise():
    """Test that on_exhausted=return_last (default) does not raise."""
    agent_config = {
        "agent_type": "test_action",
        "retry": {"on_exhausted": "return_last"},
    }

    # Pre-enriched exhausted data
    exhausted_data = {
        "source_guid": "src-return",
        "content": {},
        "metadata": {"retry_exhausted": True},
    }
    exhausted = ProcessingResult.exhausted(
        error="Retry exhausted",
        source_guid="src-return",
        recovery_metadata=_retry_metadata(),
        input_record={"target_id": "t-1"},
    )
    exhausted.data = [exhausted_data]

    # Should not raise, should return exhausted record
    output = ResultCollector.collect_results(
        [exhausted],
        agent_config,
        "test_agent",
        is_first_stage=True,
    )

    assert len(output) == 1
    assert output[0]["source_guid"] == "src-return"
