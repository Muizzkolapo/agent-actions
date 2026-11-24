"""A batch action run again with carried records lets go of its own stored file.

To decide which carried inputs to send again, submission reads the action's own stored
file. The store keeps every file it reconstructs until the next write, and a batch
action writes nothing while it prepares, so each batch file's own output stayed cached
until the walk ended (#1865). It is now dropped from the cache once its carried rows
are decided, and the decision still reconstructs the file once.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_models import SubmissionResult
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.processing.disposition_gate import DispositionGate
from agent_actions.storage.backend import DISPOSITION_SUCCESS
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "score"
FILES = [f"f{index}.json" for index in range(4)]


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


def _answered(guid: str) -> dict[str, Any]:
    return {
        "source_guid": guid,
        "content": {ACTION: {"score": 1}},
        "_state": "processed",
        "_delta_mode": "full",
    }


def _store_answers(backend: SQLiteBackend) -> None:
    """Each file holds one answered record, whose disposition says it is done."""
    for name in FILES:
        guid = f"{name}-done"
        backend._write_target_raw(ACTION, name, [_answered(guid)])
        backend.set_disposition(ACTION, guid, DISPOSITION_SUCCESS)
    backend._reconstruction_cache.clear()


def _taken(*_args: Any, record_sent: Any = None, **_kwargs: Any) -> SubmissionResult:
    if record_sent is not None:
        record_sent()
    return SubmissionResult(batch_id="batch-1")


def _service(backend: SQLiteBackend) -> BatchSubmissionService:
    """Real store and gate; preparation and the provider are stand-ins.

    Submitted with ``force=True``: the registry is a mock, whose entry reads as in flight.
    """
    preparator = MagicMock()
    preparator.turned_away.return_value = set()
    service = BatchSubmissionService(
        task_preparator=preparator,
        client_resolver=MagicMock(),
        context_manager=BatchContextManager(),
        registry_manager_factory=MagicMock(),
        storage_backend=backend,
        disposition_gate=DispositionGate(storage_backend=backend),
    )
    service._submit_to_provider = MagicMock(side_effect=_taken)  # type: ignore[method-assign]
    service._stamp_deferred = MagicMock()  # type: ignore[method-assign]

    def prepared(_config, data, *_args, **_kwargs):
        context_map = {row["source_guid"]: dict(row) for row in data}
        return [{"target_id": key} for key in context_map], context_map

    service.prepare_batch_tasks = MagicMock(side_effect=prepared)  # type: ignore[method-assign]
    return service


def _own_files_cached(backend: SQLiteBackend) -> list[str]:
    return sorted(path for action, path in backend._reconstruction_cache if action == ACTION)


def _submit(service: BatchSubmissionService, name: str, data: list[dict[str, Any]], tmp_path):
    return service.submit_batch_job(
        agent_config={"action_name": ACTION, "kind": "llm"},
        batch_name=name,
        data=data,
        output_directory=str(tmp_path / "out"),
        force=True,
        run_inputs=data,
    )


def test_each_file_is_let_go_once_its_carried_rows_are_decided(backend, tmp_path):
    _store_answers(backend)
    service = _service(backend)
    cached_after_each_file: list[list[str]] = []
    cached_while_preparing: list[list[str]] = []
    prepare = service.prepare_batch_tasks.side_effect

    def preparing(*args, **kwargs):
        cached_while_preparing.append(_own_files_cached(backend))
        return prepare(*args, **kwargs)

    service.prepare_batch_tasks.side_effect = preparing

    for name in FILES:
        data = [{"source_guid": f"{name}-done"}, {"source_guid": f"{name}-new"}]
        result = _submit(service, name, data, tmp_path)
        assert result.batch_id == "batch-1"
        cached_after_each_file.append(_own_files_cached(backend))

    # Only the new record of each file was sent; the answered one stayed carried.
    sent = [call.args[1] for call in service.prepare_batch_tasks.call_args_list]
    assert sent == [[{"source_guid": f"{name}-new"}] for name in FILES]
    assert cached_while_preparing == [[]] * len(FILES)
    assert cached_after_each_file == [[]] * len(FILES)


def test_a_file_whose_every_record_is_carried_is_let_go_too(backend, tmp_path):
    _store_answers(backend)
    service = _service(backend)
    cached_after_each_file: list[list[str]] = []

    for name in FILES:
        result = _submit(service, name, [{"source_guid": f"{name}-done"}], tmp_path)
        assert result.passthrough == {"carry_forward_only": True}
        cached_after_each_file.append(_own_files_cached(backend))

    service.prepare_batch_tasks.assert_not_called()
    assert cached_after_each_file == [[]] * len(FILES)


def test_the_carried_rows_of_a_file_are_decided_from_one_reconstruction(backend, tmp_path):
    _store_answers(backend)
    service = _service(backend)
    rebuilt: list[str] = []
    reconstruct = backend._reconstruct_from_deltas

    def counting(action_name, relative_path, rows):
        if action_name == ACTION:
            rebuilt.append(relative_path)
        return reconstruct(action_name, relative_path, rows)

    backend._reconstruct_from_deltas = counting  # type: ignore[method-assign]

    for name in FILES:
        _submit(
            service,
            name,
            [{"source_guid": f"{name}-done"}, {"source_guid": f"{name}-new"}],
            tmp_path,
        )

    assert rebuilt == FILES


def test_a_repair_that_sends_nothing_lets_its_file_go_after_writing_it(backend, tmp_path):
    _store_answers(backend)
    service = _service(backend)
    cached_after_each_file: list[list[str]] = []

    for name in FILES:
        new = f"{name}-new"
        service._disposition_gate = DispositionGate(storage_backend=backend, repairing={new})
        skipped = {
            "source_guid": new,
            "content": {},
            "_batch_filter_status": "skipped",
            "_batch_skip_reason": "guard_skip",
        }
        service.prepare_batch_tasks = MagicMock(  # type: ignore[method-assign]
            return_value=([], {"t1": skipped})
        )
        result = _submit(service, name, [{"source_guid": new}], tmp_path)
        assert result.passthrough == {"type": "written"}
        cached_after_each_file.append(_own_files_cached(backend))

    assert cached_after_each_file == [[]] * len(FILES)
