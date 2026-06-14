"""Tests for batch carry-forward merge at retrieve time.

Tests cover: parent spec items 6, 17 (cleanup part).
Carry-forward is now derived from terminal dispositions in the storage
backend, not from a filesystem file.
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
    terminal_guids: set[str] | None = None,
) -> MagicMock:
    backend = MagicMock()
    backend.list_target_files.return_value = target_files or []
    backend.get_terminal_record_ids.return_value = terminal_guids or set()

    def read_target(action_name: str, rel_path: str) -> list[dict]:
        if prior_output and rel_path in prior_output:
            return prior_output[rel_path]
        raise FileNotFoundError(f"No file: {rel_path}")

    backend.read_target.side_effect = read_target
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
            terminal_guids={f"r{i}" for i in range(9)},
        )
        service = _make_service(storage_backend=backend)

        batch_output = [{"source_guid": "r9", "score_quality": {"score": 0.7}}]
        result = service._merge_carry_forward("test_action", batch_output)

        assert len(result) == 10
        assert result[0]["source_guid"] == "r9"
        guids = {r["source_guid"] for r in result}
        assert guids == {f"r{i}" for i in range(10)}

    def test_no_terminal_guids_returns_unchanged(self):
        """No terminal dispositions -> output unchanged."""
        backend = _mock_backend(terminal_guids=set())
        service = _make_service(storage_backend=backend)

        batch_output = [{"source_guid": "r0"}]
        result = service._merge_carry_forward("test_action", batch_output)
        assert result == batch_output

    def test_carry_forward_records_have_prior_run_data(self):
        """Carry-forward records contain the action's prior output data."""
        prior_records = [
            {"source_guid": "r0", "enriched_ns": {"key": "value"}, "lineage": {"parent": "abc"}}
        ]
        backend = _mock_backend(
            target_files=["data.json"],
            prior_output={"data.json": prior_records},
            terminal_guids={"r0"},
        )
        service = _make_service(storage_backend=backend)

        result = service._merge_carry_forward("test_action", [])

        assert len(result) == 1
        assert result[0]["enriched_ns"] == {"key": "value"}
        assert result[0]["lineage"] == {"parent": "abc"}


class TestCarryForwardEdgeCases:
    def test_missing_prior_output_partial_merge(self):
        """Prior output missing for one file -> partial merge, not crash."""
        backend = _mock_backend(
            target_files=["data1.json", "data2.json"],
            prior_output={"data1.json": [{"source_guid": "r0", "data": "ok"}]},
            terminal_guids={"r0", "r1"},
        )
        service = _make_service(storage_backend=backend)

        result = service._merge_carry_forward("test_action", [])
        assert len(result) == 1
        assert result[0]["source_guid"] == "r0"

    def test_overlap_deduplication(self):
        """Overlapping GUIDs between batch and carry-forward -> deduplicated."""
        prior_records = [
            {"source_guid": "r0", "data": "old"},
            {"source_guid": "r1", "data": "old"},
        ]
        backend = _mock_backend(
            target_files=["data.json"],
            prior_output={"data.json": prior_records},
            terminal_guids={"r0", "r1"},
        )
        service = _make_service(storage_backend=backend)

        batch_output = [{"source_guid": "r0", "data": "new"}]
        result = service._merge_carry_forward("test_action", batch_output)

        assert len(result) == 2
        r0s = [r for r in result if r["source_guid"] == "r0"]
        assert len(r0s) == 1
        assert r0s[0]["data"] == "new"

    def test_no_storage_backend_returns_unchanged(self):
        """No storage backend -> output unchanged."""
        service = _make_service(storage_backend=None)

        batch_output = [{"source_guid": "r1"}]
        result = service._merge_carry_forward("test_action", batch_output)
        assert result == batch_output
