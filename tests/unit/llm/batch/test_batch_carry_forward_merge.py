"""Tests for batch carry-forward merge at retrieve time.

Tests cover: parent spec items 6, 17 (cleanup part).
What is carried is every row of the file being written that the batch did not
answer for — the rows exist and the output is replaced whole, so a row left out
is a row deleted. Their dispositions do not enter into it, and neither do the
action's other files: these rows go straight into this one.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

_sentinel = object()
if sys.modules.get("agent_actions.workflow.pipeline_file_mode", _sentinel) is _sentinel:
    sys.modules["agent_actions.workflow.pipeline_file_mode"] = MagicMock()

from agent_actions.llm.batch.services.processing import BatchProcessingService


def _make_service(
    *,
    storage_backend: Any | None = None,
    action_name: str = "test_action",
) -> BatchProcessingService:
    return BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        workflow_name=action_name,
        storage_backend=storage_backend,
    )


def _mock_backend(
    target_files: list[str] | None = None,
    prior_output: dict[str, list[dict]] | None = None,
) -> MagicMock:
    backend = MagicMock()
    backend.list_target_files.return_value = target_files or []

    def read_target(action_name: str, rel_path: str) -> list[dict]:
        if prior_output and rel_path in prior_output:
            return prior_output[rel_path]
        raise FileNotFoundError(f"No file: {rel_path}")

    backend.read_target_for_rewrite.side_effect = read_target
    return backend


class TestMergeCarryForward:
    """Spec test 6: carry-forward records merged into batch output."""

    def test_carry_forward_merged_into_output(self):
        """9 carry-forward + 1 batch-processed -> 10 in output."""
        prior_records = [
            {"source_guid": f"r{i}", "score_quality": {"score": 0.9}} for i in range(9)
        ]
        backend = _mock_backend(
            target_files=["data.json"],
            prior_output={"data.json": prior_records},
        )
        service = _make_service(storage_backend=backend)

        batch_output = [{"source_guid": "r9", "score_quality": {"score": 0.7}}]
        result = service._merge_carry_forward("test_action", batch_output, "data.json")

        assert len(result) == 10
        assert result[0]["source_guid"] == "r9"
        guids = {r["source_guid"] for r in result}
        assert guids == {f"r{i}" for i in range(10)}

    def test_no_stored_rows_returns_unchanged(self):
        """The action holds no rows of its own -> nothing to carry."""
        backend = _mock_backend()
        service = _make_service(storage_backend=backend)

        batch_output = [{"source_guid": "r0"}]
        result = service._merge_carry_forward("test_action", batch_output, "data.json")
        assert result == batch_output

    def test_carry_forward_records_have_prior_run_data(self):
        """Carry-forward records contain the action's prior output data."""
        prior_records = [
            {"source_guid": "r0", "enriched_ns": {"key": "value"}, "lineage": {"parent": "abc"}}
        ]
        backend = _mock_backend(
            target_files=["data.json"],
            prior_output={"data.json": prior_records},
        )
        service = _make_service(storage_backend=backend)

        result = service._merge_carry_forward("test_action", [], "data.json")

        assert len(result) == 1
        assert result[0]["enriched_ns"] == {"key": "value"}
        assert result[0]["lineage"] == {"parent": "abc"}


class TestCarryForwardEdgeCases:
    def test_unreadable_prior_output_is_not_a_crash(self):
        """The file being written has no stored rows yet -> nothing to carry."""
        backend = _mock_backend(target_files=["data1.json"], prior_output={})
        service = _make_service(storage_backend=backend)

        result = service._merge_carry_forward("test_action", [{"source_guid": "r9"}], "data1.json")

        assert result == [{"source_guid": "r9"}]

    def test_a_duplicate_identity_elsewhere_is_not_carried_twice(self):
        """The shape the real store was left in: a second file holding the first's
        identities. Narrowing only which identities to carry is not enough — the
        rows must be fetched from the file being written, or the duplicate in the
        other file is appended beside the real one.
        """
        backend = _mock_backend(
            target_files=["a.json", "b.json"],
            prior_output={
                "a.json": [{"source_guid": "a0"}, {"source_guid": "a1", "from": "a"}],
                "b.json": [{"source_guid": "a1", "from": "b"}],
            },
        )
        service = _make_service(storage_backend=backend)

        result = service._merge_carry_forward("test_action", [{"source_guid": "a0"}], "a.json")

        assert [r["source_guid"] for r in result] == ["a0", "a1"], (
            f"the duplicate in b.json was carried into a.json as well: {result}"
        )
        assert result[1]["from"] == "a", "the row came from the wrong file"

    def test_another_file_s_rows_are_not_pulled_in(self):
        """The defect this rule exists to stop: rows are handed straight to the
        write, so reading a file other than the one being written puts that
        file's records into this one."""
        backend = _mock_backend(
            target_files=["a.json", "b.json"],
            prior_output={
                "a.json": [{"source_guid": "a0"}, {"source_guid": "a1"}],
                "b.json": [{"source_guid": "b0"}],
            },
        )
        service = _make_service(storage_backend=backend)

        result = service._merge_carry_forward("test_action", [{"source_guid": "a0"}], "a.json")

        assert [r["source_guid"] for r in result] == ["a0", "a1"], (
            "b.json's rows were written into a.json"
        )

    def test_overlap_deduplication(self):
        """Overlapping GUIDs between batch and carry-forward -> deduplicated."""
        prior_records = [
            {"source_guid": "r0", "data": "old"},
            {"source_guid": "r1", "data": "old"},
        ]
        backend = _mock_backend(
            target_files=["data.json"],
            prior_output={"data.json": prior_records},
        )
        service = _make_service(storage_backend=backend)

        batch_output = [{"source_guid": "r0", "data": "new"}]
        result = service._merge_carry_forward("test_action", batch_output, "data.json")

        assert len(result) == 2
        r0s = [r for r in result if r["source_guid"] == "r0"]
        assert len(r0s) == 1
        assert r0s[0]["data"] == "new"

    def test_a_non_terminal_row_is_carried(self):
        """The half a terminal-disposition rule gets wrong. `failed` is not a
        terminal disposition, so a rule reading dispositions drops this row and
        leaves its disposition naming a record with no data."""
        backend = _mock_backend(
            target_files=["data.json"],
            prior_output={"data.json": [{"source_guid": "r0", "data": "kept"}]},
        )
        service = _make_service(storage_backend=backend)

        result = service._merge_carry_forward("test_action", [{"source_guid": "r1"}], "data.json")

        assert [r["source_guid"] for r in result] == ["r1", "r0"]
        backend.get_terminal_record_ids.assert_not_called()

    def test_no_storage_backend_returns_unchanged(self):
        """No storage backend -> output unchanged."""
        service = _make_service(storage_backend=None)

        batch_output = [{"source_guid": "r1"}]
        result = service._merge_carry_forward("test_action", batch_output, "data.json")
        assert result == batch_output
