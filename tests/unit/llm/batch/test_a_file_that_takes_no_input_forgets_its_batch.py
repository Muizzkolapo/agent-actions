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
