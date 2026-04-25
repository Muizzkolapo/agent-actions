"""Tests for ResultCollector and ExhaustedRecordBuilder."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import AgentActionsError
from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.result_collector import CollectionStats, ResultCollector
from agent_actions.processing.types import (
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)
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

    output, _ = ResultCollector.collect_results(
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

    output, _ = ResultCollector.collect_results(
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

    output, _ = ResultCollector.collect_results(
        [result],
        agent_config={},
        agent_name="test",
        is_first_stage=True,
    )

    assert output == []


def test_exhausted_record_builder_preserves_lineage(monkeypatch):
    monkeypatch.setattr(IDGenerator, "generate_node_id", lambda _: "action_node")
    agent_config: dict[str, Any] = {"agent_type": "builder_action"}
    original_row = {"lineage": ["root_abc123"], "target_id": "t-7"}

    exhausted_item = ExhaustedRecordBuilder.build_exhausted_item(
        source_guid="src-7",
        original_row=original_row,
        recovery_metadata=_retry_metadata(),
        agent_config=agent_config,
        action_name="builder_action",
    )

    assert exhausted_item["target_id"] == "t-7"
    assert exhausted_item["lineage"] == ["root_abc123", "action_node"]


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
        "name": "",
        "active": False,
        "count": 0,
        "score": 0,
        "tags": [],
        "meta": {},
    }

    # No schema returns empty dict
    assert ExhaustedRecordBuilder.build_empty_content({}) == {}


def test_result_collector_on_exhausted_raise():
    """Test that on_exhausted=raise throws AgentActionsError."""
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

    with pytest.raises(AgentActionsError) as exc_info:
        ResultCollector.collect_results(
            [exhausted],
            agent_config,
            "test_agent",
            is_first_stage=True,
        )

    assert "on_exhausted=raise" in str(exc_info.value)
    assert exc_info.value.context["exhausted_records"] == 1


def test_result_collector_on_exhausted_raise_writes_disposition_before_raising():
    """Disposition must be written even when on_exhausted=raise crashes the pipeline."""
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

    mock_backend = MagicMock()

    with pytest.raises(AgentActionsError):
        ResultCollector.collect_results(
            [exhausted],
            agent_config,
            "test_agent",
            is_first_stage=True,
            storage_backend=mock_backend,
        )

    # Disposition should have been written before the raise
    mock_backend.set_disposition.assert_called_once_with(
        "test_agent",
        "src-raise",
        "exhausted",
        reason="exhausted_after_2_attempts",
    )


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
    output, _ = ResultCollector.collect_results(
        [exhausted],
        agent_config,
        "test_agent",
        is_first_stage=True,
    )

    assert len(output) == 1
    assert output[0]["source_guid"] == "src-return"


# ---------------------------------------------------------------------------
# Per-record disposition write tests
# ---------------------------------------------------------------------------


class TestResultCollectorDispositions:
    """Tests for per-record disposition writes in ResultCollector."""

    def _make_backend(self):
        backend = MagicMock()
        backend.set_disposition = MagicMock()
        return backend

    def test_filtered_result_writes_disposition(self):
        backend = self._make_backend()
        filtered = ProcessingResult.filtered(source_guid="src-f1")
        filtered.skip_reason = "low_confidence"

        ResultCollector.collect_results(
            [filtered],
            {},
            "my_agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_called_once_with(
            "my_agent",
            "src-f1",
            "filtered",
            reason="low_confidence",
        )

    def test_filtered_result_default_reason(self):
        backend = self._make_backend()
        filtered = ProcessingResult.filtered(source_guid="src-f2")

        ResultCollector.collect_results(
            [filtered],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_called_once_with(
            "agent",
            "src-f2",
            "filtered",
            reason="guard_filter",
        )

    def test_failed_result_writes_disposition(self):
        backend = self._make_backend()
        failed = ProcessingResult.failed(error="timeout", source_guid="src-fail")

        ResultCollector.collect_results(
            [failed],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_called_once_with(
            "agent",
            "src-fail",
            "failed",
            reason="timeout",
            input_snapshot=None,
        )

    def test_failed_result_default_reason(self):
        """When error field is empty string, falls back to 'processing_error'."""
        backend = self._make_backend()
        failed = ProcessingResult(
            status=ProcessingStatus.FAILED,
            data=[],
            executed=False,
            error="",
            source_guid="src-fail2",
        )

        ResultCollector.collect_results(
            [failed],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_called_once_with(
            "agent",
            "src-fail2",
            "failed",
            reason="processing_error",
            input_snapshot=None,
        )

    def test_skipped_result_writes_disposition(self):
        backend = self._make_backend()
        skipped = ProcessingResult.skipped(
            passthrough_data={"content": {}},
            reason="guard_skip",
            source_guid="src-sk",
        )

        ResultCollector.collect_results(
            [skipped],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_called_once_with(
            "agent",
            "src-sk",
            "skipped",
            reason="guard_skip",
        )

    def test_exhausted_result_writes_disposition(self):
        backend = self._make_backend()
        exhausted = ProcessingResult.exhausted(
            error="Retry exhausted",
            source_guid="src-ex",
            recovery_metadata=_retry_metadata(),
        )
        exhausted.data = [{"source_guid": "src-ex", "content": {}}]

        ResultCollector.collect_results(
            [exhausted],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_called_once_with(
            "agent",
            "src-ex",
            "exhausted",
            reason="exhausted_after_2_attempts",
        )

    def test_unprocessed_result_writes_disposition(self):
        backend = self._make_backend()
        unprocessed = ProcessingResult(
            status=ProcessingStatus.UNPROCESSED,
            source_guid="src-un",
            data=[{"content": {}}],
            skip_reason="where_clause",
        )

        ResultCollector.collect_results(
            [unprocessed],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_called_once_with(
            "agent",
            "src-un",
            "unprocessed",
            reason="where_clause",
        )

    def test_success_result_no_disposition(self):
        backend = self._make_backend()
        success = ProcessingResult.success(
            data=[{"content": {"v": 1}}],
            source_guid="src-ok",
        )

        ResultCollector.collect_results(
            [success],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_not_called()

    def test_no_storage_backend_no_crash(self):
        """Dispositions are skipped gracefully when storage_backend is None."""
        filtered = ProcessingResult.filtered(source_guid="src-f")
        failed = ProcessingResult.failed(error="boom", source_guid="src-fail")

        # Should not raise
        output, _ = ResultCollector.collect_results(
            [filtered, failed],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=None,
        )
        assert output == []

    def test_no_source_guid_no_disposition(self):
        """Records without source_guid should not attempt disposition writes."""
        backend = self._make_backend()
        filtered = ProcessingResult.filtered(source_guid=None)

        ResultCollector.collect_results(
            [filtered],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_not_called()

    def test_deferred_result_writes_disposition(self):
        """DEFERRED records write a disposition with source_guid as record_id."""
        backend = self._make_backend()
        deferred = ProcessingResult.deferred(
            task_id="task-123",
            source_guid="src-def",
        )

        ResultCollector.collect_results(
            [deferred],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_called_once_with(
            "agent",
            "src-def",
            "deferred",
            reason="batch_queued:task_id=task-123",
        )

    def test_deferred_result_no_source_guid_no_disposition(self):
        """DEFERRED records without source_guid skip the disposition write."""
        backend = self._make_backend()
        deferred = ProcessingResult.deferred(
            task_id="task-456",
            source_guid=None,
        )

        ResultCollector.collect_results(
            [deferred],
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        backend.set_disposition.assert_not_called()

    def test_deferred_result_counted_in_stats(self):
        """DEFERRED records are counted in CollectionStats.deferred."""
        deferred = ProcessingResult.deferred(
            task_id="task-789",
            source_guid="src-d",
        )

        _, stats = ResultCollector.collect_results(
            [deferred],
            {},
            "agent",
            is_first_stage=False,
        )

        assert stats.deferred == 1
        assert stats.success == 0

    def test_mixed_statuses_write_correct_dispositions(self):
        """Multiple statuses in one batch write the right dispositions."""
        backend = self._make_backend()

        results = [
            ProcessingResult.success(data=[{"content": {}}], source_guid="ok"),
            ProcessingResult.filtered(source_guid="filt"),
            ProcessingResult.failed(error="err", source_guid="fail"),
        ]

        ResultCollector.collect_results(
            results,
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        assert backend.set_disposition.call_count == 2
        calls = backend.set_disposition.call_args_list
        assert calls[0] == (("agent", "filt", "filtered"), {"reason": "guard_filter"})
        assert calls[1] == (("agent", "fail", "failed"), {"reason": "err", "input_snapshot": None})

    def test_mixed_with_deferred_writes_all_dispositions(self):
        """DEFERRED + other statuses each write their own disposition."""
        backend = self._make_backend()

        results = [
            ProcessingResult.deferred(task_id="t-1", source_guid="src-d"),
            ProcessingResult.filtered(source_guid="src-f"),
        ]

        ResultCollector.collect_results(
            results,
            {},
            "agent",
            is_first_stage=False,
            storage_backend=backend,
        )

        assert backend.set_disposition.call_count == 2
        calls = backend.set_disposition.call_args_list
        assert calls[0] == (("agent", "src-d", "deferred"), {"reason": "batch_queued:task_id=t-1"})
        assert calls[1] == (("agent", "src-f", "filtered"), {"reason": "guard_filter"})


class TestCollectionStatsOnlyGuardOutcomes:
    """Tests for CollectionStats.only_guard_outcomes property.

    The property uses dataclasses.fields() to sum all stat fields, so adding
    a new field to CollectionStats automatically makes it return False when
    the new field has a non-zero count — no manual update needed.
    """

    def test_all_filtered(self):
        assert CollectionStats(filtered=5).only_guard_outcomes is True

    def test_all_skipped(self):
        assert CollectionStats(skipped=3).only_guard_outcomes is True

    def test_mixed_filtered_and_skipped(self):
        assert CollectionStats(filtered=2, skipped=3).only_guard_outcomes is True

    def test_all_zeros(self):
        """All-zero stats: 0 == 0 → True (preserves existing behavior)."""
        assert CollectionStats().only_guard_outcomes is True

    def test_unprocessed_blocks(self):
        assert CollectionStats(unprocessed=5).only_guard_outcomes is False

    def test_success_blocks(self):
        assert CollectionStats(success=1).only_guard_outcomes is False

    def test_failed_blocks(self):
        assert CollectionStats(failed=1).only_guard_outcomes is False

    def test_exhausted_blocks(self):
        assert CollectionStats(exhausted=1).only_guard_outcomes is False

    def test_deferred_blocks(self):
        assert CollectionStats(deferred=1).only_guard_outcomes is False

    def test_mixed_filtered_with_unprocessed_blocks(self):
        """Filtered + unprocessed: not all-guard, must block."""
        assert CollectionStats(filtered=3, unprocessed=2).only_guard_outcomes is False

    def test_mixed_skipped_with_success_blocks(self):
        assert CollectionStats(skipped=2, success=1).only_guard_outcomes is False
