"""Tests for DispositionGate integration in batch submission.

Tests cover: parent spec items 5, 17.
"""

from __future__ import annotations

import logging
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
    """A store where every record called done also has its stored row, as a real one does.

    One with a disposition and no row is re-queued, which is pinned against a real store in
    ``tests/integration/test_batch_rerun_matches_online.py``.
    """
    backend = MagicMock()
    backend.get_terminal_record_ids.return_value = terminal_ids
    backend.read_target_for_rewrite.return_value = [
        {"source_guid": guid, "content": {}} for guid in sorted(terminal_ids)
    ]
    return backend


def _dispositions(*, filtered: set[str]):
    def _get(action_name: str, record_id: str | None = None, disposition: str | None = None):
        if disposition != "filtered":
            return []
        return [{"record_id": guid} for guid in sorted(filtered)]

    return _get


def _sent(backend: MagicMock, inputs: list[str]) -> list[str]:
    """The inputs a submission over *inputs* hands on to preparation, in order."""
    service = _make_service(
        disposition_gate=DispositionGate(storage_backend=backend),
        storage_backend=backend,
        tasks=[{"custom_id": "t", "body": {}}],
        context_map={"t": {"source_guid": "t"}},
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        service.submit_batch_job(
            agent_config={"agent_type": "test_action", "action_name": "test_action"},
            batch_name="data.json",
            data=[_make_record(guid) for guid in inputs],
            output_directory=tmpdir,
        )
    return [record["source_guid"] for record in service.prepare_batch_tasks.call_args[0][1]]


class TestBatchDispositionGate:
    """Spec test 5: records with SUCCESS disposition excluded from batch submission."""

    def test_narrowed_records_reach_preparation_without_carry_forward(self, tmp_path):
        selected = _make_record("selected")
        gate = MagicMock(spec=DispositionGate)
        # `repairing` is a frozenset on the real gate and empty on an ordinary run;
        # left as a Mock it is truthy, which reads as a repair to every caller.
        gate.repairing = frozenset()
        gate.filter.return_value = ([selected], set())
        service = _make_service(
            disposition_gate=gate,
            tasks=[{"custom_id": "selected"}],
        )
        config = {"action_name": "test_action"}

        service.submit_batch_job(
            agent_config=config,
            batch_name="test",
            data=[_make_record("unselected"), selected],
            output_directory=str(tmp_path),
        )

        assert service.prepare_batch_tasks.call_args.args[1] == [selected]
        assert service._submit_to_provider.call_args.args[2] == [{"custom_id": "selected"}]

    def test_empty_selection_without_carry_forward_never_submits(self, tmp_path):
        gate = MagicMock(spec=DispositionGate)
        gate.repairing = frozenset()
        gate.filter.return_value = ([], set())
        service = _make_service(disposition_gate=gate, tasks=[{"custom_id": "unselected"}])

        result = service.submit_batch_job(
            agent_config={"action_name": "test_action"},
            batch_name="test",
            data=[_make_record("unselected")],
            output_directory=str(tmp_path),
        )

        assert result.batch_id is None
        service.prepare_batch_tasks.assert_not_called()
        service._submit_to_provider.assert_not_called()

    def test_a_done_input_is_looked_up_under_the_name_its_output_is_stored_under(self):
        """Finalize stores `data.json` whatever the input file is called. Looked up under
        the input's own name, every done record reads as having no row and is re-sent."""
        backend = _mock_backend(terminal_ids={"r0", "r1"})
        rows = backend.read_target_for_rewrite.return_value

        def _read(action_name: str, relative_path: str) -> list[dict]:
            if relative_path != "data.json":
                raise FileNotFoundError(relative_path)
            return rows

        backend.read_target_for_rewrite.side_effect = _read
        backend.read_checkpoint_records.return_value = []
        service = _make_service(
            disposition_gate=DispositionGate(storage_backend=backend),
            storage_backend=backend,
            tasks=[{"custom_id": "r2", "body": {}}],
            context_map={"r2": {"source_guid": "r2"}},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            service.submit_batch_job(
                agent_config={"agent_type": "test_action", "action_name": "test_action"},
                batch_name="data.jsonl",
                data=[_make_record(f"r{i}") for i in range(3)],
                output_directory=tmpdir,
            )

        sent = service.prepare_batch_tasks.call_args[0][1]
        assert [record["source_guid"] for record in sent] == ["r2"]

    def test_a_done_input_with_no_stored_row_is_sent_again(self):
        backend = _mock_backend(terminal_ids={"r0", "r1"})
        backend.read_target_for_rewrite.return_value = [{"source_guid": "r0", "content": {}}]
        service = _make_service(
            disposition_gate=DispositionGate(storage_backend=backend),
            storage_backend=backend,
            tasks=[{"custom_id": "r1", "body": {}}],
            context_map={"r1": {"source_guid": "r1"}},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            service.submit_batch_job(
                agent_config={"agent_type": "test_action", "action_name": "test_action"},
                batch_name="data.json",
                data=[_make_record("r0"), _make_record("r1")],
                output_directory=tmpdir,
            )

        sent = service.prepare_batch_tasks.call_args[0][1]
        assert [record["source_guid"] for record in sent] == ["r1"]

    def test_a_done_input_whose_answers_carry_minted_identities_is_not_sent_again(self):
        """No stored row carries the input's own identity; each names it as its producer."""
        backend = _mock_backend(terminal_ids={"r0"})
        backend.read_target_for_rewrite.return_value = [
            {"source_guid": "m1", "producer_source_guids": ["r0"], "content": {}},
            {"source_guid": "m2", "producer_source_guids": ["r0"], "content": {}},
        ]

        assert _sent(backend, ["r0", "r1"]) == ["r1"]

    def test_a_done_input_whose_row_this_run_writes_over_is_sent_again(self):
        """Its only row sits under an identity the run is processing, so that row is
        replaced and the input would be left with no answer."""
        backend = _mock_backend(terminal_ids={"r0"})
        backend.read_target_for_rewrite.return_value = [
            {"source_guid": "r1", "producer_source_guids": ["r0"], "content": {}},
        ]

        assert _sent(backend, ["r0", "r1"]) == ["r0", "r1"]

    def test_an_input_the_guard_filtered_goes_to_the_guard_again(self):
        """Online judges it afresh every run; called done here, it would never be."""
        backend = _mock_backend(terminal_ids={"r0", "r1"})
        backend.read_target_for_rewrite.return_value = [{"source_guid": "r0", "content": {}}]
        backend.get_disposition.side_effect = _dispositions(filtered={"r1"})

        assert _sent(backend, ["r0", "r1", "r2"]) == ["r1", "r2"]

    def test_a_filtered_input_is_not_reported_as_a_row_gone_missing(self, caplog):
        """It holds no row by design, so a healthy run has nothing to warn about."""
        backend = _mock_backend(terminal_ids={"r0", "r1"})
        backend.read_target_for_rewrite.return_value = [{"source_guid": "r0", "content": {}}]
        backend.get_disposition.side_effect = _dispositions(filtered={"r1"})

        with caplog.at_level(logging.WARNING):
            _sent(backend, ["r0", "r1"])

        assert "not found in prior output" not in caplog.text

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
