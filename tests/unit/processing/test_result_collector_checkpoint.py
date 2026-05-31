"""Tests for per-record checkpoint in OnlineLLMStrategy._checkpoint_record.

Uses a real SQLite backend to verify that checkpointed dispositions and
output records actually persist in the database after each LLM call.
"""

import pytest

from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _make_context(backend, action_name="action_a", file_path="output.json", output_dir="/out"):
    return ProcessingContext(
        agent_config={},
        agent_name=action_name,
        storage_backend=backend,
        file_path=f"{output_dir}/{file_path}",
        output_directory=output_dir,
    )


def _make_success_result(guid: str) -> ProcessingResult:
    return ProcessingResult(
        status=ProcessingStatus.SUCCESS,
        data=[{"source_guid": guid, "content": f"data_{guid}"}],
        source_guid=guid,
    )


def _make_failed_result(guid: str, error: str = "LLM error") -> ProcessingResult:
    return ProcessingResult(
        status=ProcessingStatus.FAILED,
        data=[],
        source_guid=guid,
        error=error,
    )


@pytest.fixture()
def backend(tmp_path):
    db = SQLiteBackend.create(
        db_path=str(tmp_path / "test.db"),
        workflow_name="test_wf",
    )
    db.initialize()
    return db


class TestCheckpointRecord:
    """Per-record checkpoint writes disposition + output to SQLite."""

    def test_success_writes_disposition_and_output(self, backend):
        """A successful record writes SUCCESS disposition and checkpoint output."""
        ctx = _make_context(backend)
        result = _make_success_result("r0")

        OnlineLLMStrategy._checkpoint_record(result, ctx)

        terminal_ids = backend.get_terminal_record_ids("action_a")
        assert "r0" in terminal_ids

        records = backend.read_checkpoint_records("action_a", "output.json")
        assert len(records) == 1
        assert records[0]["source_guid"] == "r0"

    def test_failed_writes_disposition_no_output(self, backend):
        """A failed record writes FAILED disposition but no checkpoint output (data=[])."""
        ctx = _make_context(backend)
        result = _make_failed_result("r0")

        OnlineLLMStrategy._checkpoint_record(result, ctx)

        # FAILED is not gate-terminal, so it won't show in get_terminal_record_ids
        disps = backend.get_disposition("action_a", record_id="r0")
        assert len(disps) == 1
        assert disps[0]["disposition"] == "failed"

        # No output records (data was empty)
        records = backend.read_checkpoint_records("action_a", "output.json")
        assert len(records) == 0

    def test_multiple_records_accumulate(self, backend):
        """Multiple checkpoint writes append to the checkpoint table."""
        ctx = _make_context(backend)

        for i in range(5):
            result = _make_success_result(f"r{i}")
            OnlineLLMStrategy._checkpoint_record(result, ctx)

        terminal_ids = backend.get_terminal_record_ids("action_a")
        assert len(terminal_ids) == 5

        records = backend.read_checkpoint_records("action_a", "output.json")
        assert len(records) == 5
        assert {r["source_guid"] for r in records} == {f"r{i}" for i in range(5)}

    def test_simulated_interrupt_preserves_completed(self, backend):
        """Simulate: 3 records to process, checkpoint 2, 'crash' before 3rd.

        The first 2 records should be recoverable.
        """
        ctx = _make_context(backend)

        # Process and checkpoint records 0 and 1
        for i in range(2):
            result = _make_success_result(f"r{i}")
            OnlineLLMStrategy._checkpoint_record(result, ctx)

        # "Crash" before record 2 — don't checkpoint it

        terminal_ids = backend.get_terminal_record_ids("action_a")
        assert terminal_ids == {"r0", "r1"}
        assert "r2" not in terminal_ids

        records = backend.read_checkpoint_records("action_a", "output.json")
        assert len(records) == 2

    def test_clear_after_completion(self, backend):
        """clear_checkpoint_records removes all checkpoint data."""
        ctx = _make_context(backend)

        for i in range(3):
            OnlineLLMStrategy._checkpoint_record(_make_success_result(f"r{i}"), ctx)

        assert len(backend.read_checkpoint_records("action_a", "output.json")) == 3

        backend.clear_checkpoint_records("action_a")
        assert len(backend.read_checkpoint_records("action_a", "output.json")) == 0

    def test_no_checkpoint_without_backend(self, backend):
        """No crash when storage_backend is None."""
        ctx = _make_context(backend)
        ctx.storage_backend = None

        result = _make_success_result("r0")
        OnlineLLMStrategy._checkpoint_record(result, ctx)

        # Nothing written (no backend)
        assert backend.read_checkpoint_records("action_a", "output.json") == []
