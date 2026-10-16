"""An action's failed items are every disposition `agac retry` selects, not only `failed`.

`exhausted` is a failure the user can act on, so an action holding one must not read clean.
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "test.db"), workflow_name="test_workflow")
    b.initialize()
    return b


def test_failed_and_exhausted_records_are_failed_items(backend):
    backend.set_disposition("a", "r1", "failed", reason="boom")
    backend.set_disposition("a", "r2", "exhausted", reason="exhausted_after_2_attempts")
    backend.set_disposition("a", "r3", "success")

    assert {row["record_id"] for row in backend.get_failed_items("a")} == {"r1", "r2"}


@pytest.mark.parametrize("disposition", ["success", "skipped", "filtered", "passthrough"])
def test_a_record_that_did_not_fail_is_not_a_failed_item(backend, disposition):
    backend.set_disposition("a", "r1", disposition)

    assert backend.get_failed_items("a") == []


def test_the_node_level_failure_is_not_an_item(backend):
    backend.set_disposition("a", "__node__", "failed", reason="halt")
    backend.set_disposition("a", "r1", "exhausted", reason="exhausted_after_1_attempts")

    assert [row["record_id"] for row in backend.get_failed_items("a")] == ["r1"]


def test_another_actions_exhausted_record_is_not_this_actions(backend):
    backend.set_disposition("b", "r1", "exhausted", reason="exhausted_after_1_attempts")

    assert backend.get_failed_items("a") == []
