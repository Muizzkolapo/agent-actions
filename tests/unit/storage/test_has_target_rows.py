"""Whether an action holds any stored row.

Asked of an unhealthy upstream before its skipped reader's rows are deleted, so a
wrong "none" deletes rows that should stand and a wrong "some" keeps rows made
from nothing. A file is not a row: an action whose guard filtered every record
still stores its empty list.

Every case is asked of both answers — the SQLite probe and the base-class walk
over the same store — because a backend that does not override inherits the walk.
"""

import json
import sqlite3

import pytest

from agent_actions.storage.backend import StorageBackend
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ANSWERS = {
    "sqlite": SQLiteBackend.has_target_rows,
    "base": StorageBackend.has_target_rows,
}


@pytest.fixture(params=sorted(ANSWERS))
def ask(request):
    return ANSWERS[request.param]


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "agent_io" / "t.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _content(guid, *namespaces):
    return {
        "source_guid": guid,
        "_state": "processed",
        "_state_schema_version": 1,
        "content": {ns: {"v": ns} for ns in namespaces},
    }


class TestHasTargetRows:
    def test_an_action_that_never_wrote_holds_none(self, backend, ask):
        assert ask(backend, "never_ran") is False

    def test_a_file_holding_an_empty_list_is_not_a_row(self, backend, ask):
        backend.write_target("act", "a.json", [])

        assert backend.list_target_files("act") == ["a.json"]
        assert ask(backend, "act") is False

    def test_one_file_holding_a_row_is_enough(self, backend, ask):
        backend.write_target("act", "a.json", [])
        backend.write_target("act", "b.json", [{"source_guid": "g0"}])

        assert ask(backend, "act") is True

    def test_a_row_without_an_identity_is_still_a_row(self, backend, ask):
        """target_rows_per_source_guid skips such a row; this must not, or an
        upstream holding only guid-less rows reads as empty and its reader's
        rows are deleted."""
        backend.write_target("act", "a.json", [{"summary": "x"}])

        assert backend.target_rows_per_source_guid("act") == {}
        assert ask(backend, "act") is True

    def test_a_row_stored_as_a_delta_is_a_row(self, backend, ask):
        backend.save_metadata("execution_order", json.dumps(["up", "act"]))
        backend.write_target("up", "a.json", [_content("g1", "source", "up")])
        backend.write_target("act", "a.json", [_content("g1", "source", "up", "act")])

        assert backend._read_target_raw("act", "a.json")[0]["_delta_mode"] == "delta"
        assert ask(backend, "act") is True

    def test_it_does_not_reach_into_another_action(self, backend, ask):
        backend.write_target("other", "a.json", [{"source_guid": "g9"}])
        backend.write_target("act", "a.json", [])

        assert ask(backend, "act") is False

    def test_deleting_the_target_leaves_none(self, backend, ask):
        backend.write_target("act", "a.json", [{"source_guid": "g0"}])
        backend.delete_target("act")

        assert ask(backend, "act") is False


def test_sqlite_answers_without_reading_a_row(backend, monkeypatch):
    """A cost guard: the probe exists so the question costs one indexed lookup,
    not a parse of every row the action holds."""
    backend.write_target("act", "a.json", [{"source_guid": "g0"}] * 3)

    def _refuse(*_a, **_kw):
        raise AssertionError("has_target_rows read the rows")

    monkeypatch.setattr(backend, "_read_target_raw", _refuse)

    assert backend.has_target_rows("act") is True


class TestRowsStoredBeforeRecordCountExisted:
    """A store opened by an older framework: record_count is NULL on rows written
    before the column existed, and the column the migration added is TEXT."""

    @pytest.fixture
    def legacy(self, tmp_path):
        db_path = tmp_path / "agent_io" / "legacy.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE target_data (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "action_name TEXT NOT NULL, relative_path TEXT NOT NULL, data TEXT NOT NULL, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(action_name, relative_path))"
        )
        conn.execute(
            "INSERT INTO target_data (action_name, relative_path, data) VALUES (?, ?, ?)",
            ("held", "a.json", json.dumps([{"source_guid": "g0"}])),
        )
        conn.execute(
            "INSERT INTO target_data (action_name, relative_path, data) VALUES (?, ?, ?)",
            ("emptied", "a.json", "[]"),
        )
        conn.commit()
        conn.close()
        b = SQLiteBackend(str(db_path), "wf")
        b.initialize()
        yield b
        b.close()

    def test_a_null_count_is_measured_from_the_data(self, legacy, ask):
        assert ask(legacy, "held") is True
        assert ask(legacy, "emptied") is False

    def test_a_zero_count_in_the_migrated_text_column_holds_none(self, legacy, ask):
        """'0' > 0 is true in SQLite: text sorts above every number."""
        legacy.write_target("filtered", "a.json", [])
        legacy.write_target("kept", "a.json", [{"source_guid": "g1"}] * 10)

        stored = legacy.connection.execute(
            "SELECT typeof(record_count) FROM target_data WHERE action_name = 'filtered'"
        ).fetchone()[0]
        assert stored == "text"
        assert ask(legacy, "filtered") is False
        assert ask(legacy, "kept") is True


class TestBaseClassWalk:
    def test_a_file_listed_but_gone_holds_none(self):
        """Listing and reading are two calls, and a file can go between them."""

        class Vanishing(SQLiteBackend):
            def list_target_files(self, action_name):
                return ["gone.json"]

            def _read_target_raw(self, action_name, relative_path):
                raise FileNotFoundError(relative_path)

        assert StorageBackend.has_target_rows(Vanishing(":memory:", "wf"), "act") is False
