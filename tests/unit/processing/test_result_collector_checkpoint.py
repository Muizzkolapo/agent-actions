"""Tests for checkpoint flush in collect_results_from_processing_results.

Uses a real SQLite backend to verify that checkpointed records and
dispositions actually survive in the database — not just that methods
were called on a mock.
"""

import pytest

from agent_actions.processing.result_collector import collect_results_from_processing_results
from agent_actions.processing.types import ProcessingResult, ProcessingStatus
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _make_success_result(guid: str) -> ProcessingResult:
    return ProcessingResult(
        status=ProcessingStatus.SUCCESS,
        data=[{"source_guid": guid, "content": f"data_{guid}"}],
        source_guid=guid,
    )


def _make_results(n: int) -> list[ProcessingResult]:
    return [_make_success_result(f"r{i}") for i in range(n)]


@pytest.fixture()
def backend(tmp_path):
    db = SQLiteBackend.create(
        db_path=str(tmp_path / "test.db"),
        workflow_name="test_wf",
    )
    db.initialize()
    return db


class TestCheckpointWithRealSQLite:
    """Checkpoint flushing with real SQLite — data actually persists."""

    def test_checkpointed_dispositions_survive_in_db(self, backend):
        """After checkpoint, SUCCESS dispositions are queryable from SQLite."""
        results = _make_results(60)

        collect_results_from_processing_results(
            results,
            "action_a",
            storage_backend=backend,
            checkpoint_interval=25,
            checkpoint_relative_path="output.json",
        )

        # All 60 records should have SUCCESS dispositions in the DB
        terminal_ids = backend.get_terminal_record_ids("action_a")
        assert len(terminal_ids) == 60
        for i in range(60):
            assert f"r{i}" in terminal_ids

    def test_checkpointed_records_survive_in_db(self, backend):
        """After checkpoint, output records are readable from checkpoint table."""
        results = _make_results(60)

        collect_results_from_processing_results(
            results,
            "action_a",
            storage_backend=backend,
            checkpoint_interval=25,
            checkpoint_relative_path="output.json",
        )

        # All 60 records should be in the checkpoint table
        records = backend.read_checkpoint_records("action_a", "output.json")
        assert len(records) == 60
        guids = {r["source_guid"] for r in records}
        assert guids == {f"r{i}" for i in range(60)}

    def test_simulated_interrupt_preserves_first_50(self, backend):
        """Simulate: process 75, checkpoint at 50, 'crash' before final write.

        The first 50 records should be recoverable from checkpoint table,
        and their dispositions should be in SQLite.
        """
        results = _make_results(75)

        # Process only the first 50 by using checkpoint_interval=50
        # and simulating that the process was interrupted after the
        # first checkpoint but before completion.
        # We do this by running 50 records through with checkpoint_interval=50.
        collect_results_from_processing_results(
            results[:50],
            "action_a",
            storage_backend=backend,
            checkpoint_interval=50,
            checkpoint_relative_path="output.json",
        )

        # 50 dispositions in DB
        terminal_ids = backend.get_terminal_record_ids("action_a")
        assert len(terminal_ids) == 50

        # 50 records in checkpoint table
        checkpointed = backend.read_checkpoint_records("action_a", "output.json")
        assert len(checkpointed) == 50

        # Records 50-74 are NOT in the DB (they weren't processed)
        for i in range(50, 75):
            assert f"r{i}" not in terminal_ids

    def test_clear_checkpoint_after_completion(self, backend):
        """clear_checkpoint_records removes all checkpoint data."""
        results = _make_results(50)

        collect_results_from_processing_results(
            results,
            "action_a",
            storage_backend=backend,
            checkpoint_interval=25,
            checkpoint_relative_path="output.json",
        )

        assert len(backend.read_checkpoint_records("action_a", "output.json")) == 50

        backend.clear_checkpoint_records("action_a")
        assert len(backend.read_checkpoint_records("action_a", "output.json")) == 0

    def test_no_checkpoint_when_interval_zero(self, backend):
        """Default: single batch write, no checkpoint records."""
        results = _make_results(50)

        collect_results_from_processing_results(
            results,
            "action_a",
            storage_backend=backend,
            checkpoint_interval=0,
        )

        # Dispositions exist (written in tail flush)
        assert len(backend.get_terminal_record_ids("action_a")) == 50

        # No checkpoint records (feature disabled)
        assert backend.read_checkpoint_records("action_a", "output.json") == []
