"""Test: checkpoint resume for first-stage actions.

First-stage input records arrive without source_guid. The fix assigns
a deterministic content-hash guid BEFORE the DispositionGate runs,
so the same input record gets the same guid across runs.
"""

import pytest

from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.storage.backend import DISPOSITION_SUCCESS
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.utils.id_generation import IDGenerator


@pytest.fixture()
def backend(tmp_path):
    db = SQLiteBackend.create(db_path=str(tmp_path / "test.db"), workflow_name="test_wf")
    db.initialize()
    return db


def _raw_input_records():
    """Input records as they come from staging — NO source_guid."""
    return [
        {"id": "page1", "url": "https://example.com/1", "page_content": "content 1"},
        {"id": "page2", "url": "https://example.com/2", "page_content": "content 2"},
        {"id": "page3", "url": "https://example.com/3", "page_content": "content 3"},
    ]


class TestDeterministicGuidAssignment:
    """Content-hash guid is deterministic across runs."""

    def test_same_record_gets_same_guid(self):
        """Same input dict produces the same content-hash guid."""
        record = {"id": "page1", "url": "https://example.com/1", "page_content": "content 1"}
        guid1 = IDGenerator.generate_content_hash(record)
        guid2 = IDGenerator.generate_content_hash(record)
        assert guid1 == guid2

    def test_different_records_get_different_guids(self):
        """Different input dicts produce different guids."""
        record_a = {"id": "page1", "content": "aaa"}
        record_b = {"id": "page2", "content": "bbb"}
        assert IDGenerator.generate_content_hash(record_a) != IDGenerator.generate_content_hash(
            record_b
        )


class TestFirstStageCheckpointResume:
    """First-stage checkpoint resume with deterministic guid assignment."""

    def test_gate_matches_after_guid_assignment(self, backend):
        """Assign content-hash guids, checkpoint one, re-run — gate carries it forward."""
        records = _raw_input_records()

        # Simulate first run: assign guids, process record 0, checkpoint it
        for r in records:
            r["source_guid"] = IDGenerator.generate_content_hash(r)

        first_guid = records[0]["source_guid"]
        backend.set_disposition("action_a", first_guid, DISPOSITION_SUCCESS)

        # Simulate second run: same input records, assign guids again
        records_run2 = _raw_input_records()
        for r in records_run2:
            r["source_guid"] = IDGenerator.generate_content_hash(r)

        # Guid is deterministic — same content → same guid
        assert records_run2[0]["source_guid"] == first_guid

        # Gate should carry forward record 0, process records 1-2
        gate = DispositionGate(storage_backend=backend)
        to_process, carry_ids = gate.filter(records_run2, "action_a")

        assert carry_ids == {first_guid}
        assert len(to_process) == 2

    def test_records_without_guid_get_no_match(self, backend):
        """Without guid assignment, gate can't match — all reprocessed (the bug)."""
        records = _raw_input_records()
        for r in records:
            r["source_guid"] = IDGenerator.generate_content_hash(r)

        backend.set_disposition("action_a", records[0]["source_guid"], DISPOSITION_SUCCESS)

        # Second run WITHOUT assigning guids
        records_no_guid = _raw_input_records()

        gate = DispositionGate(storage_backend=backend)
        to_process, carry_ids = gate.filter(records_no_guid, "action_a")

        assert len(carry_ids) == 0  # Bug: can't match
        assert len(to_process) == 3  # All reprocessed
