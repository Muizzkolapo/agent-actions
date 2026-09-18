"""Tests for DispositionGate integration in batch submission.

Tests cover: parent spec items 5, 17.
"""

from __future__ import annotations

import sys
import tempfile
from typing import Any
from unittest.mock import MagicMock

_sentinel = object()
if sys.modules.get("agent_actions.workflow.pipeline_file_mode", _sentinel) is _sentinel:
    sys.modules["agent_actions.workflow.pipeline_file_mode"] = MagicMock()

from agent_actions.llm.batch.services.submission import BatchSubmissionService
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
        service.prepare_batch_tasks = MagicMock(return_value=(tasks, context_map or {}))

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

            # Carry-forward is now derived from dispositions at merge time —
            # no file is written. The 9 terminal records were filtered out
            # and only 1 record was submitted (verified above).

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


class TestBatchAllCarryForward:
    """All records carried -> no batch submission."""

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

            assert result.batch_id is None
            assert result.passthrough == {"carry_forward_only": True}


class TestCarryForwardDispositionDerived:
    """Carry-forward is derived from terminal dispositions, not a file."""

    def test_terminal_records_filtered_by_gate(self):
        """Terminal records are filtered by DispositionGate before submission."""
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

            args = service.prepare_batch_tasks.call_args
            submitted_data = args[0][1]
            assert len(submitted_data) == 1
            assert submitted_data[0]["source_guid"] == "r2"
