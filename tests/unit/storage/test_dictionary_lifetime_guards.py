"""The guards that keep a compressed row's dictionary alive as long as a row needs it.

Each one protects a production path (a retry's scoped clear, a resume's per-file
checkpoint clear, a writer after one of its own writes rolled back) and each would
regress by one token with the suite otherwise green.
"""

import json
import sqlite3

import pytest

from agent_actions.errors.processing import SerializationError
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"
FILE = "pages.json"
BODY = "the quick brown fox jumps over the lazy dog. " * 40


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
        "content": {ACTION: {"summary": f"Page {n}: {BODY}"}},
    }


def _summaries(rows: list[dict]) -> list[str]:
    return [row["content"][ACTION]["summary"] for row in rows]


@pytest.fixture
def db(tmp_path):
    return tmp_path / "wf.db"


@pytest.fixture
def backend(db):
    b = SQLiteBackend(str(db), workflow_name="wf")
    b.initialize()
    yield b
    b.close()


def _fresh_reader(db) -> SQLiteBackend:
    return SQLiteBackend.create_readonly(db)


def test_clearing_one_records_disposition_keeps_the_others_snapshots_readable(backend, db):
    first = json.dumps({"source_guid": "guid-1", "content": {"page_content": BODY}})
    second = json.dumps({"source_guid": "guid-2", "content": {"page_content": BODY[::-1]}})
    backend.set_disposition(ACTION, "guid-1", "failed", input_snapshot=first)
    backend.set_disposition(ACTION, "guid-2", "exhausted", input_snapshot=second)

    backend.clear_disposition(ACTION, record_id="guid-1")

    reader = _fresh_reader(db)
    try:
        assert [r["input_snapshot"] for r in reader.get_disposition(ACTION)] == [second]
    finally:
        reader.close()


def test_clearing_one_paths_checkpoints_keeps_the_other_paths_readable(backend, db):
    backend.save_checkpoint_records(ACTION, "a.json", [_record(0)])
    backend.save_checkpoint_records(ACTION, "b.json", [_record(1), _record(2)])

    backend.clear_checkpoint_records(ACTION, "a.json")

    reader = _fresh_reader(db)
    try:
        assert _summaries(reader.read_checkpoint_records(ACTION, "b.json")) == _summaries(
            [_record(1), _record(2)]
        )
    finally:
        reader.close()


def test_the_writer_itself_reads_a_write_after_one_of_its_own_rolled_back(backend):
    """A rolled-back insert frees its dictionary id, which the next write may be given;
    a writer that cached the first would decode the second against the wrong bytes."""
    backend.connection.execute(
        "CREATE TRIGGER refuse_a BEFORE INSERT ON target_data WHEN NEW.action_name = 'a'"
        " BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    backend.connection.commit()

    with pytest.raises(sqlite3.Error):
        backend.write_target("a", FILE, [_record(0)], force_full=True)
    backend.write_target("b", FILE, [_record(1), _record(2)], force_full=True)

    assert _summaries(backend.read_target("b", FILE)) == _summaries([_record(1), _record(2)])


def test_clearing_every_actions_traces_leaves_records_readable(backend, db):
    backend.write_prompt_trace(ACTION, "tid-0", "Summarise the page. " * 30)
    backend.write_target(ACTION, FILE, [_record(0), _record(1)], force_full=True)

    backend.clear_prompt_traces()

    reader = _fresh_reader(db)
    try:
        assert _summaries(reader.read_target(ACTION, FILE)) == _summaries([_record(0), _record(1)])
    finally:
        reader.close()


def test_a_text_row_that_is_not_json_is_an_error_naming_the_file(backend):
    backend.connection.execute(
        "INSERT INTO target_data (action_name, relative_path, data, record_count)"
        " VALUES (?, ?, 'not json at all', 1)",
        (ACTION, FILE),
    )
    backend.connection.commit()

    with pytest.raises(SerializationError, match=rf"target_data.*{ACTION}.*{FILE}"):
        backend.read_target(ACTION, FILE)


def test_a_run_path_that_asks_for_no_snapshots_never_decodes_one(backend):
    """A corrupt forensic blob must not fail a reader that only wants ids and dispositions."""
    backend.set_disposition(ACTION, "guid-1", "failed", input_snapshot=json.dumps({"n": 1}))
    backend.connection.execute(
        "UPDATE record_disposition SET input_snapshot = ?", (b"\x00\x00\x00\x00not zlib",)
    )
    backend.connection.commit()

    rows = backend.get_disposition(ACTION, snapshots=False)
    assert [(r["record_id"], r["disposition"]) for r in rows] == [("guid-1", "failed")]
    assert "input_snapshot" not in rows[0]
    with pytest.raises(SerializationError, match="guid-1"):
        backend.get_disposition(ACTION)
