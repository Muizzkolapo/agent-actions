"""Tests for DispositionGate integration in batch submission.

Tests cover: parent spec items 5, 17.
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

from agent_actions.llm.batch.services.submission import (
    BATCH_CARRY_FORWARD_FILENAME,
    BatchSubmissionService,
)
from agent_actions.processing.disposition_gate import DispositionGate


def _make_service(
    *,
    disposition_gate: DispositionGate | None = None,
    storage_backend: Any | None = None,
    tasks: list[dict] | None = None,
    context_map: dict | None = None,
) -> BatchSubmissionService:
    """Create a BatchSubmissionService with mocked dependencies."""
    preparator = MagicMock()
    client_resolver = MagicMock()
    context_manager = MagicMock()
    registry_manager_factory = MagicMock()

    # Configure registry manager to not find existing jobs
    registry_mgr = MagicMock()
    registry_mgr.get_batch_job.return_value = None
    registry_manager_factory.return_value = registry_mgr

    service = BatchSubmissionService(
        task_preparator=preparator,
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
        storage_backend=storage_backend,
        disposition_gate=disposition_gate,
    )

    # Mock prepare_batch_tasks to return given tasks/context_map
    if tasks is not None:
        service.prepare_batch_tasks = MagicMock(
            return_value=(tasks, context_map or {})
        )

    # Mock _submit_to_provider to return a successful submission
    submitted = MagicMock()
    submitted.batch_id = "batch_123"
    submitted.is_submitted = True
    service._submit_to_provider = MagicMock(return_value=submitted)

    return service


def _make_record(guid: str) -> dict:
    return {"source_guid": guid, "content": {}}


def _mock_backend(terminal_ids: set[str]) -> MagicMock:
    backend = MagicMock()
    backend.get_terminal_record_ids.return_value = terminal_ids
    return backend


class TestBatchDispositionGate:
    """Spec test 5: records with SUCCESS disposition excluded from batch submission."""

    def test_terminal_records_filtered_before_prepare(self):
        """9 with success + 1 cleared → 1 task prepared."""
        terminal = {f"r{i}" for i in range(9)}
        backend = _mock_backend(terminal_ids=terminal)
        gate = DispositionGate(storage_backend=backend)

        with tempfile.TemporaryDirectory() as tmpdir:
            # The task list returned by prepare_batch_tasks (after filtering)
            service = _make_service(
                disposition_gate=gate,
                storage_backend=backend,
                tasks=[{"custom_id": "r9", "body": {}}],
                context_map={"r9": {"source_guid": "r9"}},
            )

            records = [_make_record(f"r{i}") for i in range(10)]
            config = {"agent_type": "test_action", "action_name": "test_action"}

            service.submit_batch_job(
                agent_config=config,
                batch_name="test",
                data=records,
                output_directory=tmpdir,
            )

            # prepare_batch_tasks called with only the 1 cleared record
            args = service.prepare_batch_tasks.call_args
            submitted_data = args[0][1]  # second positional arg is `data`
            assert len(submitted_data) == 1
            assert submitted_data[0]["source_guid"] == "r9"

            # Carry-forward file written
            carry_path = Path(tmpdir) / "batch" / BATCH_CARRY_FORWARD_FILENAME
            assert carry_path.exists()
            carry_data = json.loads(carry_path.read_text())
            assert set(carry_data["guids"]) == terminal

    def test_no_gate_all_records_submitted(self):
        """Backward compatibility: no gate = all records to preparator."""
        with tempfile.TemporaryDirectory() as tmpdir:
            service = _make_service(
                disposition_gate=None,
                tasks=[{"custom_id": f"r{i}"} for i in range(10)],
            )

            records = [_make_record(f"r{i}") for i in range(10)]
            config = {"agent_type": "test_action", "action_name": "test_action"}

            service.submit_batch_job(
                agent_config=config,
                batch_name="test",
                data=records,
                output_directory=tmpdir,
            )

            args = service.prepare_batch_tasks.call_args
            submitted_data = args[0][1]
            assert len(submitted_data) == 10

            # No carry-forward file
            carry_path = Path(tmpdir) / "batch" / BATCH_CARRY_FORWARD_FILENAME
            assert not carry_path.exists()


class TestBatchAllCarryForward:
    """All records carried → no batch submission."""

    def test_all_terminal_skips_submission(self):
        terminal = {f"r{i}" for i in range(5)}
        backend = _mock_backend(terminal_ids=terminal)
        gate = DispositionGate(storage_backend=backend)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = _make_service(
                disposition_gate=gate,
                storage_backend=backend,
            )

            records = [_make_record(f"r{i}") for i in range(5)]
            config = {"agent_type": "test_action", "action_name": "test_action"}

            result = service.submit_batch_job(
                agent_config=config,
                batch_name="test",
                data=records,
                output_directory=tmpdir,
            )

            # No batch submitted
            assert result.batch_id is None
            assert result.passthrough == {"carry_forward_only": True}

            # Carry-forward file still written
            carry_path = Path(tmpdir) / "batch" / BATCH_CARRY_FORWARD_FILENAME
            assert carry_path.exists()
            carry_data = json.loads(carry_path.read_text())
            assert set(carry_data["guids"]) == terminal


class TestCarryForwardFileLifecycle:
    """Spec test 17: carry-forward file lifecycle."""

    def test_stale_file_cleaned_when_no_carry_forward(self):
        """Stale .batch_carry_forward.json removed on next run with no carry-forward."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create stale carry-forward file
            batch_dir = Path(tmpdir) / "batch"
            batch_dir.mkdir(parents=True)
            carry_path = batch_dir / BATCH_CARRY_FORWARD_FILENAME
            carry_path.write_text('{"guids": ["stale"]}')

            service = _make_service(
                disposition_gate=DispositionGate(storage_backend=None),  # no-op gate
                tasks=[{"custom_id": "r0"}],
                context_map={"r0": {"source_guid": "r0"}},
            )

            records = [_make_record("r0")]
            config = {"agent_type": "test_action", "action_name": "test_action"}

            service.submit_batch_job(
                agent_config=config,
                batch_name="test",
                data=records,
                output_directory=tmpdir,
            )

            # Stale file cleaned up
            assert not carry_path.exists()

    def test_carry_forward_file_written_atomically(self):
        """Carry-forward file exists after write with correct content."""
        terminal = {"r0", "r1"}
        backend = _mock_backend(terminal_ids=terminal)
        gate = DispositionGate(storage_backend=backend)

        with tempfile.TemporaryDirectory() as tmpdir:
            service = _make_service(
                disposition_gate=gate,
                storage_backend=backend,
                tasks=[{"custom_id": "r2"}],
                context_map={"r2": {"source_guid": "r2"}},
            )

            records = [_make_record("r0"), _make_record("r1"), _make_record("r2")]
            config = {"agent_type": "test_action", "action_name": "test_action"}

            service.submit_batch_job(
                agent_config=config,
                batch_name="test",
                data=records,
                output_directory=tmpdir,
            )

            carry_path = Path(tmpdir) / "batch" / BATCH_CARRY_FORWARD_FILENAME
            assert carry_path.exists()
            data = json.loads(carry_path.read_text())
            # GUIDs sorted deterministically
            assert data["guids"] == sorted(terminal)
