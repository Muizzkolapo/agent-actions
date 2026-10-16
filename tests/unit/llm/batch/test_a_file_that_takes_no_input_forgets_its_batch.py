"""A file that takes no input keeps none of the state its last batch left."""

from unittest.mock import MagicMock

from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryStateManager
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"


def _service(backend):
    return BatchSubmissionService(
        task_preparator=MagicMock(),
        client_resolver=MagicMock(),
        context_manager=BatchContextManager(),
        registry_manager_factory=MagicMock(),
        storage_backend=backend,
    )


def _keys(backend, file_name):
    return sorted(
        key
        for key in (
            RecoveryStateManager._metadata_key(ACTION, file_name),
            BatchContextManager._metadata_key(ACTION, file_name),
            BatchContextManager._inputs_key(ACTION, file_name),
        )
        if backend.load_metadata(key) is not None
    )


def test_its_context_map_inputs_and_recovery_state_go_and_another_files_stay(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    for file_name in ("a.json", "b.json"):
        backend.save_metadata(RecoveryStateManager._metadata_key(ACTION, file_name), "{}")
        backend.save_metadata(BatchContextManager._metadata_key(ACTION, file_name), "{}")
        backend.save_metadata(BatchContextManager._inputs_key(ACTION, file_name), "[]")

    _service(backend)._forget_the_batch_of(backend, ACTION, "b.json")

    assert _keys(backend, "b.json") == []
    assert len(_keys(backend, "a.json")) == 3


def _write_for(backend, tmp_path, run_inputs):
    guids = [row["source_guid"] for row in run_inputs]
    _service(backend)._write_for_inputs_carried(
        "summarize", "b.json", str(tmp_path), run_inputs, guids
    )


def _store_with_state_for_b(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    backend.save_metadata(BatchContextManager._metadata_key(ACTION, "b.json"), "{}")
    return backend


def test_a_file_the_run_narrowed_to_nothing_keeps_its_state(tmp_path):
    """Its input is not empty: a guard or record limit left nothing to send."""
    backend = _store_with_state_for_b(tmp_path)

    _write_for(backend, tmp_path, [{"source_guid": "r1"}])

    assert len(_keys(backend, "b.json")) == 1


def test_a_file_that_took_no_input_loses_its_state_when_it_is_written(tmp_path):
    backend = _store_with_state_for_b(tmp_path)

    _write_for(backend, tmp_path, [])

    assert _keys(backend, "b.json") == []
