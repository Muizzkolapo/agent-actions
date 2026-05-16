"""Tests for cascade_filter — record-level quarantine before strategy invocation."""

from agent_actions.processing.cascade_filter import partition_cascade_records
from agent_actions.processing.types import ProcessingStatus
from agent_actions.record.reasons import UPSTREAM_UNPROCESSED
from tests.helpers.cascade_helpers import make_record as _record


class TestPartitionCascadeRecords:
    """partition_cascade_records splits records by CASCADE_BLOCKING state."""

    def test_all_active_records_pass_through(self):
        records = [_record("r1", "active"), _record("r2", "active")]
        processable, quarantined = partition_cascade_records(records, action_name="test_action")
        assert len(processable) == 2
        assert len(quarantined) == 0

    def test_no_state_records_pass_through(self):
        """Records without _state (e.g. first-stage) are processable."""
        records = [_record("r1"), _record("r2")]
        processable, quarantined = partition_cascade_records(records, action_name="test_action")
        assert len(processable) == 2
        assert len(quarantined) == 0

    def test_failed_record_quarantined(self):
        records = [_record("r1", "active"), _record("r2", "failed")]
        processable, quarantined = partition_cascade_records(records, action_name="test_action")
        assert len(processable) == 1
        assert processable[0]["source_guid"] == "r1"
        assert len(quarantined) == 1
        assert quarantined[0].status == ProcessingStatus.UNPROCESSED
        assert quarantined[0].source_guid == "r2"

    def test_exhausted_record_quarantined(self):
        records = [_record("r1", "active"), _record("r2", "exhausted")]
        processable, quarantined = partition_cascade_records(records, action_name="test_action")
        assert len(processable) == 1
        assert len(quarantined) == 1
        assert quarantined[0].source_guid == "r2"

    def test_cascade_skipped_record_quarantined(self):
        records = [_record("r1", "active"), _record("r2", "cascade_skipped")]
        processable, quarantined = partition_cascade_records(records, action_name="test_action")
        assert len(processable) == 1
        assert len(quarantined) == 1

    def test_mixed_states(self):
        """Multiple blocking states intermixed with active records."""
        records = [
            _record("r1", "active"),
            _record("r2", "failed"),
            _record("r3", "active"),
            _record("r4", "exhausted"),
            _record("r5", "cascade_skipped"),
        ]
        processable, quarantined = partition_cascade_records(records, action_name="test_action")
        assert [r["source_guid"] for r in processable] == ["r1", "r3"]
        assert len(quarantined) == 3

    def test_all_quarantined(self):
        """When all records are cascade-blocked, processable is empty."""
        records = [_record("r1", "failed"), _record("r2", "exhausted")]
        processable, quarantined = partition_cascade_records(records, action_name="test_action")
        assert len(processable) == 0
        assert len(quarantined) == 2

    def test_empty_input(self):
        processable, quarantined = partition_cascade_records([], action_name="test_action")
        assert processable == []
        assert quarantined == []

    def test_quarantined_result_has_tombstone_data(self):
        """Quarantined results carry a tombstone record with lineage fields."""
        records = [_record("r1", "failed")]
        _, quarantined = partition_cascade_records(records, action_name="test_action")
        result = quarantined[0]
        assert result.data is not None
        assert len(result.data) == 1
        tombstone = result.data[0]
        assert tombstone["source_guid"] == "r1"
        assert tombstone["metadata"]["reason"] == UPSTREAM_UNPROCESSED
        assert tombstone["metadata"]["agent_type"] == "tombstone"

    def test_quarantined_result_reason(self):
        records = [_record("r1", "cascade_skipped")]
        _, quarantined = partition_cascade_records(records, action_name="test_action")
        assert quarantined[0].skip_reason == UPSTREAM_UNPROCESSED

    def test_processable_preserves_order(self):
        """Processable records maintain original ordering."""
        records = [
            _record("r1", "active"),
            _record("r2", "failed"),
            _record("r3", "active"),
            _record("r4", "active"),
        ]
        processable, _ = partition_cascade_records(records, action_name="test_action")
        assert [r["source_guid"] for r in processable] == ["r1", "r3", "r4"]

    def test_processed_state_not_quarantined(self):
        """PROCESSED records are resettable, not cascade-blocking."""
        records = [_record("r1", "processed")]
        processable, quarantined = partition_cascade_records(records, action_name="test_action")
        assert len(processable) == 1
        assert len(quarantined) == 0

    def test_guard_skipped_not_quarantined(self):
        """GUARD_SKIPPED records are resettable, not cascade-blocking."""
        records = [_record("r1", "guard_skipped")]
        processable, quarantined = partition_cascade_records(records, action_name="test_action")
        assert len(processable) == 1
        assert len(quarantined) == 0
