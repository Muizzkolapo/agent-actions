"""Tests for checkpoint resume via DispositionGate carry-forward.

Verifies end-to-end: checkpointed records in checkpoint_output table
are carried forward by the DispositionGate when target_data is missing
(interrupted run before save_main_output).
"""

from unittest.mock import MagicMock

from agent_actions.processing.disposition_gate import build_carry_forward


def _make_record(guid: str) -> dict:
    return {"source_guid": guid, "content": f"data_{guid}"}


class TestCheckpointResume:
    """Resume after interrupt using checkpointed records."""

    def test_carry_forward_from_checkpoint_when_target_missing(self):
        """Checkpointed records are used when target_data raises FileNotFoundError."""
        backend = MagicMock()
        backend.read_target.side_effect = FileNotFoundError("no target yet")

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
        backend.read_target.side_effect = FileNotFoundError("no target")
        backend.read_checkpoint_records.return_value = []

        carry_ids = {"r0", "r1", "r2"}
        found, missing = build_carry_forward(carry_ids, "action_a", "output.json", backend)

        assert found == []
        assert missing == carry_ids

    def test_target_exists_uses_target_not_checkpoint(self):
        """When target_data exists, checkpoint table is not consulted."""
        backend = MagicMock()
        backend.read_target.return_value = [_make_record("r0"), _make_record("r1")]

        carry_ids = {"r0", "r1"}
        found, missing = build_carry_forward(carry_ids, "action_a", "output.json", backend)

        assert len(found) == 2
        assert missing == set()
        backend.read_checkpoint_records.assert_not_called()
