"""A circuit-broken action's rows go when an upstream it waits on holds no row (1230).

Over a real store: whether an upstream "holds rows" is the storage question the
drop turns on, and a mock would answer it however the test wanted.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import ActionExecutor, ExecutorDependencies

READER_CONFIG = {"dependencies": ["up"]}


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "t.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _executor(backend):
    state = MagicMock()
    state.execution_order = ["up", "reader"]
    runner = MagicMock()
    runner.storage_backend = backend
    runner.retried_records = frozenset()
    return ActionExecutor(
        deps=ExecutorDependencies(
            action_runner=runner,
            state_manager=state,
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=MagicMock(),
        )
    )


def test_an_upstream_holding_only_an_empty_file_takes_the_readers_rows(backend):
    """A guard that filters every record still stores the empty list."""
    backend.write_target("up", "a.json", [])
    backend.write_target("reader", "a.json", [{"source_guid": "g0"}])

    _executor(backend)._drop_rows_read_from_nothing("reader", READER_CONFIG)

    assert backend.has_target_rows("reader") is False


def test_an_upstream_holding_rows_without_an_identity_leaves_the_readers_rows(backend):
    backend.write_target("up", "a.json", [{"summary": "x"}])
    backend.write_target("reader", "a.json", [{"source_guid": "g0"}])

    _executor(backend)._drop_rows_read_from_nothing("reader", READER_CONFIG)

    assert backend.has_target_rows("reader") is True


def test_a_source_named_only_in_the_context_scope_is_not_an_upstream(backend):
    """The reader ran past it, so rows built while it held nothing are not stale for it."""
    backend.write_target("up", "a.json", [{"source_guid": "g0"}])
    backend.write_target("side", "a.json", [])
    backend.write_target("reader", "a.json", [{"source_guid": "g0"}])
    executor = _executor(backend)
    executor.deps.state_manager.execution_order = ["up", "side", "reader"]

    executor._drop_rows_read_from_nothing(
        "reader",
        {"dependencies": ["up"], "context_scope": {"observe": ["up.summary", "side.summary"]}},
    )

    assert backend.has_target_rows("reader") is True


def test_a_version_base_named_in_dependencies_is_not_an_empty_upstream(backend):
    """`dependencies: [vote]` names the base, which holds nothing; vote_1 and vote_2 hold rows."""
    for name in ("vote_1", "vote_2", "merge"):
        backend.write_target(name, "a.json", [{"source_guid": "g0"}])
    executor = _executor(backend)
    executor.deps.state_manager.execution_order = ["vote_1", "vote_2", "merge"]

    executor._drop_rows_read_from_nothing(
        "merge",
        {
            "dependencies": ["vote"],
            "version_consumption_config": {"source": "vote", "pattern": "merge"},
        },
    )

    assert backend.has_target_rows("merge") is True


def test_a_repair_keeps_every_row(backend):
    """A retry touches only the records it names."""
    backend.write_target("up", "a.json", [])
    backend.write_target("reader", "a.json", [{"source_guid": "g0"}])
    executor = _executor(backend)
    executor.deps.action_runner.retried_records = frozenset({"g0"})

    executor._drop_rows_read_from_nothing("reader", READER_CONFIG)

    assert backend.has_target_rows("reader") is True


def test_what_called_the_rows_done_goes_with_them(backend):
    """With the rows gone, carry-forward falls back to checkpoints and success dispositions."""
    backend.write_target("up", "a.json", [])
    backend.write_target("reader", "a.json", [{"source_guid": "g0"}])
    backend.set_disposition("reader", "g0", "success")
    backend.save_checkpoint_records("reader", "a.json", [{"source_guid": "g0"}])

    _executor(backend)._drop_rows_read_from_nothing("reader", READER_CONFIG)

    assert backend.has_target_rows("reader") is False
    assert backend.get_disposition("reader", record_id="g0") == []
    assert backend.read_checkpoint_records("reader", "a.json") == []


def test_a_delete_that_fails_only_warns(backend, monkeypatch, caplog):
    backend.write_target("up", "a.json", [])
    backend.write_target("reader", "a.json", [{"source_guid": "g0"}])

    def refuse(action_name):
        raise OSError("disk gone")

    monkeypatch.setattr(backend, "delete_target", refuse)

    _executor(backend)._drop_rows_read_from_nothing("reader", READER_CONFIG)

    assert "Could not delete stored rows of skipped 'reader'" in caplog.text


def test_a_store_that_cannot_say_whether_it_holds_rows_keeps_the_readers(backend, monkeypatch):
    """A wrong 'holds rows' only keeps rows; a wrong 'holds none' deletes them."""
    backend.write_target("up", "a.json", [])
    backend.write_target("reader", "a.json", [{"source_guid": "g0"}])

    def cannot_say(action_name):
        raise RuntimeError("locked")

    monkeypatch.setattr(backend, "has_target_rows", cannot_say)

    _executor(backend)._drop_rows_read_from_nothing("reader", READER_CONFIG)

    monkeypatch.undo()
    assert backend.has_target_rows("reader") is True


def test_rows_stay_when_forgetting_what_called_them_done_fails(backend, monkeypatch, caplog):
    """Deleted rows with their checkpoints left behind would be served again by carry-forward."""
    backend.write_target("up", "a.json", [])
    backend.write_target("reader", "a.json", [{"source_guid": "g0"}])

    def refuse(action_name):
        raise OSError("locked")

    monkeypatch.setattr(backend, "clear_checkpoint_records", refuse)

    _executor(backend)._drop_rows_read_from_nothing("reader", READER_CONFIG)

    assert backend.has_target_rows("reader") is True
    assert "Could not delete stored rows of skipped 'reader'" in caplog.text
