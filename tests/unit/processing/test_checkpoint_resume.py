"""Tests for checkpoint resume via DispositionGate carry-forward.

Verifies end-to-end: checkpointed records in checkpoint_output table
are carried forward by the DispositionGate when target_data is missing
(interrupted run before save_main_output).
"""

import logging
from unittest.mock import MagicMock

from agent_actions.processing.disposition_gate import (
    DispositionGate,
    answered_since_stored,
    build_carry_forward,
    checkpointed_answers,
)
from agent_actions.processing.strategies.online_llm import OnlineLLMStrategy
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _make_record(guid: str) -> dict:
    return {"source_guid": guid, "content": f"data_{guid}"}


def _two_rows_one_older_one_carried():
    """r0 answered with two rows, r1 checkpointed by an earlier version, r2 with one row."""
    backend = MagicMock()
    backend.read_target_for_rewrite.side_effect = FileNotFoundError("no target yet")
    backend.read_checkpoint_records.return_value = [
        {"source_guid": "r0", "content": "first of r0"},
        {"source_guid": "r0", "content": "second of r0"},
        _make_record("r1"),
        _make_record("r2"),
    ]
    backend.checkpointed_without_row_count.return_value = {"r1"}
    return backend


class TestCheckpointResume:
    """Resume after interrupt using checkpointed records."""

    def test_carry_forward_from_checkpoint_when_target_missing(self):
        """Checkpointed records are used when target_data raises FileNotFoundError."""
        backend = MagicMock()
        backend.read_target_for_rewrite.side_effect = FileNotFoundError("no target yet")

        checkpointed = [_make_record("r0"), _make_record("r1"), _make_record("r2")]
        backend.read_checkpoint_records.return_value = checkpointed

        carry_ids = {"r0", "r1", "r2", "r3", "r4"}
        found, missing = build_carry_forward(carry_ids, "action_a", "output.json", backend)

        # r0-r2 found in checkpoint, r3-r4 missing → reprocess
        assert len(found) == 3
        assert {r["source_guid"] for r in found} == {"r0", "r1", "r2"}
        assert missing == {"r3", "r4"}

    def test_no_checkpoint_no_target_reprocesses_all(self):
        """No checkpoint and no target → all records reprocessed."""
        backend = MagicMock()
        backend.read_target_for_rewrite.side_effect = FileNotFoundError("no target")
        backend.read_checkpoint_records.return_value = []

        carry_ids = {"r0", "r1", "r2"}
        found, missing = build_carry_forward(carry_ids, "action_a", "output.json", backend)

        assert found == []
        assert missing == carry_ids

    def test_target_exists_uses_target_not_checkpoint(self):
        """When target_data exists, checkpoint table is not consulted."""
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = [_make_record("r0"), _make_record("r1")]

        carry_ids = {"r0", "r1"}
        found, missing = build_carry_forward(carry_ids, "action_a", "output.json", backend)

        assert len(found) == 2
        assert missing == set()
        backend.read_checkpoint_records.assert_not_called()

    def test_a_record_checkpointed_with_several_rows_is_answered_again(self):
        """Its rows share the record's identity until enrichment gives each its own, and a
        checkpoint row is saved before that: carried, they would be stored under one."""
        backend = MagicMock()
        backend.read_target_for_rewrite.side_effect = FileNotFoundError("no target yet")
        backend.read_checkpoint_records.return_value = [
            {"source_guid": "r0", "content": "first of r0"},
            {"source_guid": "r0", "content": "second of r0"},
            _make_record("r1"),
        ]

        found, missing = build_carry_forward({"r0", "r1"}, "action_a", "output.json", backend)

        assert found == [_make_record("r1")]
        assert missing == {"r0"}

    def test_a_record_an_earlier_version_checkpointed_is_answered_again(self):
        """That version kept one row per record, the last it was answered with, so the row
        cannot say whether the record had others."""
        backend = MagicMock()
        backend.read_target_for_rewrite.side_effect = FileNotFoundError("no target yet")
        backend.read_checkpoint_records.return_value = [_make_record("r0"), _make_record("r1")]
        backend.checkpointed_without_row_count.return_value = {"r0"}

        found, missing = build_carry_forward({"r0", "r1"}, "action_a", "output.json", backend)

        assert found == [_make_record("r1")]
        assert missing == {"r0"}

    def test_a_record_answered_again_is_not_reported_as_lost(self, caplog):
        """Its rows are in the checkpoint, so the warning for carried records nothing holds
        would point the user at a loss that did not happen."""
        with caplog.at_level(logging.INFO, logger="agent_actions.processing.disposition_gate"):
            build_carry_forward(
                {"r0", "r1", "r2"}, "action_a", "output.json", _two_rows_one_older_one_carried()
            )

        messages = [record.getMessage() for record in caplog.records]
        assert not [m for m in messages if "not found in prior output" in m]
        assert [m for m in messages if "2 checkpointed record(s)" in m and "answered again" in m]

    def test_the_checkpointed_records_counted_as_carried_are_the_ones_carried(self, caplog):
        with caplog.at_level(logging.INFO, logger="agent_actions.processing.disposition_gate"):
            build_carry_forward(
                {"r0", "r1", "r2"}, "action_a", "output.json", _two_rows_one_older_one_carried()
            )

        assert "using 1 checkpointed records for carry-forward" in caplog.text


class TestFirstStageCheckpointResume:
    def test_a_checkpointed_first_stage_record_is_carried_and_the_rest_reprocessed(self, tmp_path):
        backend = SQLiteBackend.create(db_path=str(tmp_path / "test.db"), workflow_name="wf")
        backend.initialize()
        action, relative_path = "summarize", "pages.json"
        records = [{"source_guid": f"g{i}", "id": f"page{i}"} for i in range(3)]
        try:
            context = ProcessingContext(
                agent_config={},
                agent_name=action,
                is_first_stage=True,
                storage_backend=backend,
                file_path=str(tmp_path / "output" / relative_path),
                output_directory=str(tmp_path / "output"),
                target_relative_path=relative_path,
                source_data=records,
            )
            answered = {
                "source_guid": "g0",
                "content": {"summary": "Summary of page0"},
                "target_id": "t0",
                "node_id": action,
            }
            OnlineLLMStrategy._checkpoint_record(
                ProcessingResult(
                    status=ProcessingStatus.SUCCESS, data=[answered], source_guid="g0"
                ),
                context,
            )

            to_process, carry_ids = DispositionGate(storage_backend=backend).filter(
                [dict(r) for r in records], action
            )
            carried, missing = build_carry_forward(carry_ids, action, relative_path, backend)
        finally:
            backend.close()

        assert carry_ids == {"g0"}
        assert [r["source_guid"] for r in to_process] == ["g1", "g2"]
        assert missing == set()
        assert [(r["source_guid"], r["content"]) for r in carried] == [
            ("g0", {"summary": "Summary of page0"})
        ]


class TestAnsweredSinceStored:
    """A file's checkpoint rows are cleared when it is written, so the ones left are
    answers its stored rows do not hold."""

    def test_a_record_checkpointed_beside_its_stored_file_is_named(self):
        backend = MagicMock()
        backend.read_target_for_rewrite.return_value = [_make_record("r0"), _make_record("r1")]
        backend.read_checkpoint_records.return_value = [_make_record("r1")]

        assert answered_since_stored(backend, "action_a", "output.json") == {"r1"}

    def test_a_checkpoint_with_nothing_stored_is_left_to_be_carried(self):
        backend = MagicMock()
        backend.read_target_for_rewrite.side_effect = FileNotFoundError("no target yet")
        backend.read_checkpoint_records.return_value = [_make_record("r0")]

        assert answered_since_stored(backend, "action_a", "output.json") == set()


class TestCheckpointedAnswers:
    """The checkpoint rows that stand as the answers of the records named, one per record."""

    def test_only_the_records_named_with_one_row_of_this_version_are_answered(self):
        rows = checkpointed_answers(
            _two_rows_one_older_one_carried(), "action_a", "output.json", {"r0", "r1", "r2"}
        )

        assert rows == [_make_record("r2")]

    def test_a_record_not_named_is_not_answered(self):
        rows = checkpointed_answers(
            _two_rows_one_older_one_carried(), "action_a", "output.json", {"r9"}
        )

        assert rows == []

    def test_naming_nothing_reads_nothing(self):
        backend = MagicMock()

        assert checkpointed_answers(backend, "action_a", "output.json", set()) == []
        backend.read_checkpoint_records.assert_not_called()
