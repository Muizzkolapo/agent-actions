"""Tests for batch carry-forward merge at retrieve time.

Tests cover: parent spec items 6, 17 (cleanup part).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Avoid circular import: pipeline_file_mode → workflow → ... → unified
_sentinel = object()
if sys.modules.get("agent_actions.workflow.pipeline_file_mode", _sentinel) is _sentinel:
    sys.modules["agent_actions.workflow.pipeline_file_mode"] = MagicMock()

from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.submission import BATCH_CARRY_FORWARD_FILENAME


def _make_service(
    *,
    storage_backend: Any | None = None,
    action_name: str = "test_action",
) -> BatchProcessingService:
    """Create a BatchProcessingService with minimal mocked dependencies."""
    return BatchProcessingService(
        client_resolver=MagicMock(),
        context_manager=MagicMock(),
        result_processor=MagicMock(),
        registry_manager_factory=MagicMock(),
        action_name=action_name,
        storage_backend=storage_backend,
    )


def _mock_backend(
    target_files: list[str] | None = None,
    prior_output: dict[str, list[dict]] | None = None,
) -> MagicMock:
    """Create a mock storage backend.

    Args:
        target_files: list of relative paths returned by list_target_files
        prior_output: map of rel_path → record list for read_target
    """
    backend = MagicMock()
    backend.list_target_files.return_value = target_files or []

    def read_target(action_name: str, rel_path: str) -> list[dict]:
        if prior_output and rel_path in prior_output:
            return prior_output[rel_path]
        raise FileNotFoundError(f"No file: {rel_path}")

    backend.read_target.side_effect = read_target
    return backend


def _write_carry_forward(tmpdir: str, guids: list[str]) -> Path:
    batch_dir = Path(tmpdir) / "batch"
    batch_dir.mkdir(parents=True, exist_ok=True)
    carry_path = batch_dir / BATCH_CARRY_FORWARD_FILENAME
    carry_path.write_text(json.dumps({"guids": guids}))
    return carry_path


class TestMergeCarryForward:
    """Spec test 6: carry-forward records merged into batch output."""

    def test_carry_forward_merged_into_output(self):
        """9 carry-forward + 1 batch-processed → 10 in output."""
        prior_records = [
            {"source_guid": f"r{i}", "score_quality": {"score": 0.9}} for i in range(9)
        ]
        backend = _mock_backend(
            target_files=["data.json"],
            prior_output={"data.json": prior_records},
        )
        service = _make_service(storage_backend=backend)

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_carry_forward(tmpdir, [f"r{i}" for i in range(9)])

            batch_output = [{"source_guid": "r9", "score_quality": {"score": 0.7}}]
            result = service._merge_carry_forward("test_action", batch_output, tmpdir)

            assert len(result) == 10
            # Batch-processed record first, carry-forward appended
            assert result[0]["source_guid"] == "r9"
            guids = {r["source_guid"] for r in result}
            assert guids == {f"r{i}" for i in range(10)}

    def test_no_carry_forward_file_returns_unchanged(self):
        """No .batch_carry_forward.json → output unchanged."""
        service = _make_service()

        with tempfile.TemporaryDirectory() as tmpdir:
            batch_output = [{"source_guid": "r0"}]
            result = service._merge_carry_forward("test_action", batch_output, tmpdir)
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

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_carry_forward(tmpdir, ["r0"])

            result = service._merge_carry_forward("test_action", [], tmpdir)

            assert len(result) == 1
            assert result[0]["enriched_ns"] == {"key": "value"}
            assert result[0]["lineage"] == {"parent": "abc"}


class TestCarryForwardEdgeCases:
    def test_malformed_json_returns_unchanged(self):
        """Malformed .batch_carry_forward.json → output unchanged, warning logged."""
        service = _make_service()

        with tempfile.TemporaryDirectory() as tmpdir:
            batch_dir = Path(tmpdir) / "batch"
            batch_dir.mkdir(parents=True)
            (batch_dir / BATCH_CARRY_FORWARD_FILENAME).write_text("not json")

            batch_output = [{"source_guid": "r0"}]
            result = service._merge_carry_forward("test_action", batch_output, tmpdir)
            assert result == batch_output

    def test_empty_guids_returns_unchanged(self):
        """{"guids": []} → output unchanged."""
        service = _make_service()

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_carry_forward(tmpdir, [])

            batch_output = [{"source_guid": "r0"}]
            result = service._merge_carry_forward("test_action", batch_output, tmpdir)
            assert result == batch_output

    def test_missing_prior_output_partial_merge(self):
        """Prior output missing for one file → partial merge, not crash."""
        backend = _mock_backend(
            target_files=["data1.json", "data2.json"],
            prior_output={"data1.json": [{"source_guid": "r0", "data": "ok"}]},
            # data2.json raises FileNotFoundError
        )
        service = _make_service(storage_backend=backend)

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_carry_forward(tmpdir, ["r0", "r1"])

            result = service._merge_carry_forward("test_action", [], tmpdir)
            # Only r0 found (from data1.json); r1 missing (data2.json not found)
            assert len(result) == 1
            assert result[0]["source_guid"] == "r0"

    def test_overlap_deduplication(self):
        """Overlapping GUIDs between batch and carry-forward → deduplicated."""
        prior_records = [
            {"source_guid": "r0", "data": "old"},
            {"source_guid": "r1", "data": "old"},
        ]
        backend = _mock_backend(
            target_files=["data.json"],
            prior_output={"data.json": prior_records},
        )
        service = _make_service(storage_backend=backend)

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_carry_forward(tmpdir, ["r0", "r1"])

            # r0 appears in both batch output and carry-forward
            batch_output = [{"source_guid": "r0", "data": "new"}]
            result = service._merge_carry_forward("test_action", batch_output, tmpdir)

            # batch_output r0 kept (preferred), carry-forward r0 dropped
            assert len(result) == 2
            r0s = [r for r in result if r["source_guid"] == "r0"]
            assert len(r0s) == 1
            assert r0s[0]["data"] == "new"

    def test_no_storage_backend_returns_unchanged(self):
        """No storage backend → can't read prior output → output unchanged."""
        service = _make_service(storage_backend=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            _write_carry_forward(tmpdir, ["r0"])

            batch_output = [{"source_guid": "r1"}]
            result = service._merge_carry_forward("test_action", batch_output, tmpdir)
            assert result == batch_output


class TestCarryForwardFileCleanup:
    """Spec test 17 (cleanup part)."""

    def test_file_deleted_after_merge(self):
        """Carry-forward file cleaned up after successful merge."""
        backend = _mock_backend(
            target_files=["data.json"],
            prior_output={"data.json": [{"source_guid": "r0"}]},
        )
        service = _make_service(storage_backend=backend)

        with tempfile.TemporaryDirectory() as tmpdir:
            carry_path = _write_carry_forward(tmpdir, ["r0"])
            assert carry_path.exists()

            service._merge_carry_forward("test_action", [], tmpdir)
            assert not carry_path.exists()
