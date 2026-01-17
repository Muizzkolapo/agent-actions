"""Tests for ResultCollector and ExhaustedRecordBuilder."""

from typing import Any, Dict

from agent_actions.core.exhausted_record_builder import ExhaustedRecordBuilder
from agent_actions.core.result_collector import ResultCollector
from agent_actions.core.types import (
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)
from agent_actions.utilities.id_generation import IDGenerator


def _retry_metadata() -> RecoveryMetadata:
    return RecoveryMetadata(
        retry=RetryMetadata(
            attempts=2,
            failures=2,
            succeeded=False,
            reason="timeout",
        )
    )


def test_result_collector_aggregates_statuses_first_stage(monkeypatch):
    monkeypatch.setattr(IDGenerator, "generate_node_id", lambda _: "action_node")
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
    exhausted = ProcessingResult.exhausted(
        error="Retry exhausted",
        source_guid="src-3",
        recovery_metadata=_retry_metadata(),
        input_record={"target_id": "t-1", "lineage": ["prev"]},
        source_snapshot={"target_id": "t-ignored", "lineage": ["ignored"]},
    )
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


def test_result_collector_uses_source_snapshot_downstream(monkeypatch):
    monkeypatch.setattr(IDGenerator, "generate_node_id", lambda _: "action_node")
    agent_config = {"agent_type": "downstream"}
    exhausted = ProcessingResult.exhausted(
        error="Retry exhausted",
        source_guid="src-9",
        recovery_metadata=_retry_metadata(),
        input_record={"lineage": ["input"], "target_id": "t-input"},
        source_snapshot={"lineage": ["snapshot"], "target_id": "t-snapshot"},
    )

    output = ResultCollector.collect_results(
        [exhausted],
        agent_config,
        "downstream",
        is_first_stage=False,
    )

    exhausted_item = output[0]
    assert exhausted_item["target_id"] == "t-snapshot"
    assert exhausted_item["lineage"] == ["snapshot", "action_node"]


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
