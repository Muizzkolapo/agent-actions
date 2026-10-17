"""The upstream cause on an ``upstream_unprocessed`` tombstone, on routes the CLI test misses (1429)."""

from __future__ import annotations

from agent_actions.processing.cascade_filter import partition_cascade_records
from agent_actions.record.envelope import STATE_HISTORY_CAP
from agent_actions.workflow.merge import merge_fan_in


def _entry(action: str, to: str, reason: str) -> dict:
    return {
        "timestamp": "2026-01-01T00:00:00+00:00",
        "action": action,
        "from": None,
        "to": to,
        "reason": reason,
        "detail": None,
    }


def _quarantined_metadata(record: dict, action: str = "below") -> dict:
    processable, quarantined = partition_cascade_records([record], action_name=action)
    assert not processable
    (result,) = quarantined
    (tombstone,) = result.data
    return tombstone["metadata"]


def test_a_fan_in_tainted_by_its_second_branch_names_that_branch():
    healthy = {
        "source_guid": "r1",
        "content": {"left": {"x": 1}},
        "_state": "processed",
        "_state_history": [_entry("left", "processed", "success")],
    }
    failed = {
        "source_guid": "r1",
        "content": {"right": None},
        "_state": "failed",
        "_state_history": [_entry("right", "failed", "the model failed")],
    }
    (merged,) = merge_fan_in([("left", [healthy]), ("right", [failed])])
    assert merged["_state"] == "cascade_skipped"

    metadata = _quarantined_metadata(merged, "join")

    assert metadata["upstream_action"] == "right"
    assert metadata["upstream_state"] == "failed"
    assert metadata["upstream_reason"] == "the model failed"


def test_the_first_cause_survives_a_history_capped_past_it():
    record = {
        "source_guid": "r1",
        "content": {},
        "_state": "exhausted",
        "_state_history": [_entry("first", "exhausted", "retry_exhausted")],
    }
    for n in range(STATE_HISTORY_CAP + 5):
        _, (result,) = partition_cascade_records([record], action_name=f"step_{n}")
        record = result.data[0]
        stamp = _entry(f"step_{n}", "cascade_skipped", "upstream_unprocessed")
        record["_state"] = "cascade_skipped"
        record["_state_history"] = (record["_state_history"] + [stamp])[-STATE_HISTORY_CAP:]

    assert all(e["action"] != "first" for e in record["_state_history"])
    metadata = _quarantined_metadata(record, "last")
    assert metadata["upstream_action"] == "first"
    assert metadata["upstream_state"] == "exhausted"
    assert metadata["upstream_reason"] == "retry_exhausted"


def test_a_cascade_skip_that_is_not_a_failure_says_so():
    record = {
        "source_guid": "r1",
        "content": {},
        "_state": "cascade_skipped",
        "_state_history": [_entry("summarize", "cascade_skipped", "batch_not_returned")],
    }

    metadata = _quarantined_metadata(record)

    assert metadata["upstream_action"] == "summarize"
    assert metadata["upstream_state"] == "cascade_skipped"
    assert metadata["upstream_reason"] == "batch_not_returned"


def test_a_record_with_no_history_still_names_the_state_it_came_in():
    metadata = _quarantined_metadata({"source_guid": "r1", "content": {}, "_state": "failed"})

    assert metadata["upstream_state"] == "failed"
    assert "upstream_action" not in metadata
