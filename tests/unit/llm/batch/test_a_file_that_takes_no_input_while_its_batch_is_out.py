"""A file recorded as taking no input while its batch is out is stored empty when collected."""

import pytest

from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.services.collect import write_batch_file
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    return store


def test_the_record_is_kept_per_file(backend):
    BatchContextManager.record_no_input(backend, ACTION, "a.json")

    assert BatchContextManager.takes_no_input(backend, ACTION, "a.json")
    assert not BatchContextManager.takes_no_input(backend, ACTION, "b.json")


@pytest.mark.parametrize(
    "superseded_by",
    [
        lambda store: BatchContextManager.save_batch_inputs(store, ACTION, ["r1"], "a.json"),
        lambda store: BatchContextManager.clear_batch_inputs(store, ACTION, "a.json"),
        lambda store: store.clear_batch_state(ACTION),
    ],
    ids=["inputs_recorded_again", "inputs_cleared", "action_reset"],
)
def test_it_goes_once_the_file_is_recorded_again_or_reset(backend, superseded_by):
    BatchContextManager.record_no_input(backend, ACTION, "a.json")

    superseded_by(backend)

    assert not BatchContextManager.takes_no_input(backend, ACTION, "a.json")


def test_a_file_that_takes_no_input_is_written_empty_over_what_it_held(backend, tmp_path):
    stored = [{"source_guid": "r1", "_state": "processed", "content": {}}]
    write_batch_file(backend, ACTION, stored, output_root=str(tmp_path), stored_name="a.json")

    write_batch_file(
        backend,
        ACTION,
        [{"source_guid": "r1", "_state": "processed", "content": {}}],
        output_root=str(tmp_path),
        stored_name="a.json",
        batch_inputs=["r1"],
        takes_no_input=True,
    )

    assert backend.read_target_for_rewrite(ACTION, "a.json") == []
