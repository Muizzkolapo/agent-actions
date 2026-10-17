"""The running tally of rows an action's runs have collected."""

import threading

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "store.db"), "wf")
    backend.initialize()
    yield backend
    backend.close()


def test_an_action_nothing_was_credited_to_has_collected_no_rows(backend):
    assert backend.rows_collected("never_ran") == 0


def test_credits_add_up_per_action(backend):
    backend.credit_rows_collected("a", 4)
    backend.credit_rows_collected("a", 4)
    backend.credit_rows_collected("b", 1)

    assert backend.rows_collected("a") == 8
    assert backend.rows_collected("b") == 1


def test_a_run_that_replaces_stored_rows_still_moves_the_tally(backend):
    backend.write_target("a", "f.json", [{"source_guid": "g1", "content": {"a": {"x": 1}}}])
    before = backend.rows_collected("a")

    backend.write_target("a", "f.json", [{"source_guid": "g1", "content": {"a": {"x": 2}}}])
    backend.credit_rows_collected("a", 1)

    assert backend.get_storage_stats()["nodes"]["a"] == 1
    assert backend.rows_collected("a") - before == 1


def test_credits_from_parallel_actions_are_not_lost(backend):
    def credit():
        for _ in range(500):
            backend.credit_rows_collected("a", 1)

    threads = [threading.Thread(target=credit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert backend.rows_collected("a") == 4000
