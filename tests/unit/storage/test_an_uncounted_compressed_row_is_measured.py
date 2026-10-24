"""A compressed row whose record_count is NULL is measured from the file itself.

The writer always stores the count beside a compressed file, so only a store edited
from outside holds such a row; SQLite's ``json_array_length`` cannot read it, and a
wrong "no rows" would mark an action skipped.
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "classify"


def _record(n: int) -> dict:
    return {
        "source_guid": f"guid-{n}",
        "target_id": f"tid-{n}",
        "node_id": f"{ACTION}_node",
        "lineage": [],
        "metadata": {},
        "_state": "processed",
        "_state_history": [],
        "_state_schema_version": 1,
        "content": {ACTION: {"label": f"label {n} " + "words " * 30}},
    }


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "wf.db"), workflow_name="wf")
    b.initialize()
    yield b
    b.close()


def _forget_counts(backend):
    backend.connection.execute("UPDATE target_data SET record_count = NULL")
    backend.connection.commit()


def test_rows_are_still_seen_without_their_count(backend):
    backend.write_target(ACTION, "a.json", [_record(0), _record(1)], force_full=True)
    backend.write_target(ACTION, "b.json", [_record(2)], force_full=True)
    _forget_counts(backend)

    assert backend.has_target_rows(ACTION) is True
    preview = backend.preview_target(ACTION, limit=10)
    assert preview["total_count"] == 3
    assert [r["source_guid"] for r in preview["records"]] == ["guid-0", "guid-1", "guid-2"]
    assert backend.preview_target(ACTION, limit=1, offset=2)["records"][0]["_file"] == "b.json"


def test_an_empty_file_without_its_count_holds_no_rows(backend):
    backend.write_target(ACTION, "a.json", [], force_full=True)
    _forget_counts(backend)

    assert backend.has_target_rows(ACTION) is False
    assert backend.preview_target(ACTION)["total_count"] == 0
