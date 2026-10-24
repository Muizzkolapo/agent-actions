"""The store's payload columns are compressed inside the backend and read back as written.

``target_data.data``, ``source_data.data``, ``checkpoint_output.record_data`` and
``record_disposition.input_snapshot`` are read on the resume and retry paths, so a value
that cannot be read is an error that names its row, never empty data.
"""

import json
import sqlite3
import zlib

import pytest

from agent_actions.errors.processing import SerializationError
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"
FILE = "pages.json"
BODY = "the quick brown fox jumps over the lazy dog. " * 40


def _record(n: int) -> dict:
    """A row as the pipeline stores it, lifecycle fields included."""
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


def _records(count: int = 5) -> list[dict]:
    return [_record(n) for n in range(count)]


def _source(n: int, **extra) -> dict:
    return {"source_guid": f"guid-{n}", "content": {"page_content": BODY, "n": n}, **extra}


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


def _stored(backend, table: str, column: str) -> list[tuple[str, int | None]]:
    rows = backend.connection.execute(
        f"SELECT typeof({column}), length({column}) FROM {table} ORDER BY id"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _fresh_reader(db) -> SQLiteBackend:
    return SQLiteBackend.create_readonly(db)


class TestTargetData:
    def test_a_file_is_stored_smaller_than_its_json(self, backend):
        records = _records()
        backend.write_target(ACTION, FILE, records, force_full=True)

        ((kind, size),) = _stored(backend, "target_data", "data")
        assert kind == "blob"
        assert size * 3 < len(json.dumps(records).encode())

    def test_every_reader_returns_the_records_written(self, backend, db):
        records = _records()
        backend.write_target(ACTION, FILE, records, force_full=True)

        assert _summaries(backend.read_target(ACTION, FILE)) == _summaries(records)
        assert _summaries(backend.read_target_for_rewrite(ACTION, FILE)) == _summaries(records)
        assert _summaries(backend._read_target_raw_batch([ACTION], FILE)[ACTION]) == _summaries(
            records
        )
        preview = backend.preview_target(ACTION, limit=2, offset=3)
        assert preview["total_count"] == 5
        assert _summaries(preview["records"]) == _summaries(records[3:])
        assert [r["_file"] for r in preview["records"]] == [FILE, FILE]
        scanned = backend.scan_data()["nodes"][ACTION]
        assert scanned["record_count"] == 5
        assert [r["content"]["summary"] for r in scanned["preview"]] == _summaries(records)
        assert backend.has_target_rows(ACTION) is True
        assert backend.get_storage_stats()["nodes"] == {ACTION: 5}

        reader = _fresh_reader(db)
        try:
            assert _summaries(reader.read_target(ACTION, FILE)) == _summaries(records)
        finally:
            reader.close()

    def test_every_file_of_an_action_shares_one_dictionary(self, backend):
        backend.write_target(ACTION, "a.json", _records(2), force_full=True)
        backend.write_target(ACTION, "b.json", _records(3), force_full=True)
        backend.write_target("classify", "a.json", _records(1), force_full=True)

        keys = backend.connection.execute(
            "SELECT action_name, column_name FROM prompt_trace_dictionary ORDER BY id"
        ).fetchall()
        assert [tuple(k) for k in keys] == [
            (ACTION, "target_data.data"),
            ("classify", "target_data.data"),
        ]
        assert len(backend.read_target(ACTION, "b.json")) == 3

    def test_a_row_stored_as_text_still_reads_back(self, backend):
        legacy = _records(2)
        backend.connection.execute(
            "INSERT INTO target_data (action_name, relative_path, data, record_count)"
            " VALUES ('legacy', ?, ?, NULL)",
            (FILE, json.dumps(legacy)),
        )
        backend.connection.commit()
        backend.write_target(ACTION, FILE, _records(1), force_full=True)

        assert _summaries(backend.read_target("legacy", FILE)) == _summaries(legacy)
        assert backend.has_target_rows("legacy") is True
        assert backend.preview_target("legacy")["total_count"] == 2

    def test_deleting_an_action_and_writing_again_reads_back_elsewhere(self, backend, db):
        backend.write_target(ACTION, FILE, _records(3), force_full=True)
        backend.delete_target(ACTION)
        rewritten = [{**_record(7), "content": {ACTION: {"summary": "a new wording entirely"}}}]
        backend.write_target(ACTION, FILE, rewritten, force_full=True)

        reader = _fresh_reader(db)
        try:
            assert _summaries(reader.read_target(ACTION, FILE)) == ["a new wording entirely"]
        finally:
            reader.close()

    def test_clearing_an_actions_traces_leaves_its_records_readable(self, backend, db):
        backend.write_prompt_trace(ACTION, "tid-0", "Summarise the page. " * 30)
        backend.write_target(ACTION, FILE, _records(2), force_full=True)

        backend.clear_prompt_traces(ACTION)

        reader = _fresh_reader(db)
        try:
            assert _summaries(reader.read_target(ACTION, FILE)) == _summaries(_records(2))
            assert reader.get_prompt_traces(ACTION) == []
        finally:
            reader.close()

    def test_a_failed_write_leaves_later_writes_readable_elsewhere(self, backend, db):
        backend.connection.execute(
            "CREATE TRIGGER refuse_a BEFORE INSERT ON target_data WHEN NEW.action_name = 'a'"
            " BEGIN SELECT RAISE(ABORT, 'refused'); END"
        )
        backend.connection.commit()

        with pytest.raises(sqlite3.Error):
            backend.write_target("a", FILE, _records(1), force_full=True)
        backend.write_target("b", FILE, _records(2), force_full=True)

        reader = _fresh_reader(db)
        try:
            assert _summaries(reader.read_target("b", FILE)) == _summaries(_records(2))
            with pytest.raises(FileNotFoundError):
                reader.read_target("a", FILE)
        finally:
            reader.close()

    def test_a_corrupt_row_is_an_error_naming_the_file(self, backend):
        backend.write_target(ACTION, FILE, _records(1), force_full=True)
        backend.connection.execute(
            "UPDATE target_data SET data = ? WHERE action_name = ?",
            (b"\x00\x00\x00\x00not a zlib stream", ACTION),
        )
        backend.connection.commit()

        for read in (
            lambda: backend.read_target(ACTION, FILE),
            lambda: backend.preview_target(ACTION),
            lambda: backend._read_target_raw_batch([ACTION], FILE),
        ):
            with pytest.raises(SerializationError, match=rf"target_data.*{ACTION}.*{FILE}"):
                read()

    def test_a_row_naming_a_missing_dictionary_is_an_error(self, backend):
        backend.write_target(ACTION, FILE, _records(1), force_full=True)
        backend.connection.execute(
            "UPDATE target_data SET data = ? WHERE action_name = ?",
            ((999).to_bytes(4, "big") + zlib.compress(b"[]"), ACTION),
        )
        backend.connection.commit()

        with pytest.raises(SerializationError, match=r"dictionary 999"):
            backend.read_target(ACTION, FILE)


class TestSourceData:
    def test_rows_are_stored_smaller_and_read_back(self, backend):
        rows = [_source(n) for n in range(4)]
        backend.write_source(FILE, rows)

        stored = _stored(backend, "source_data", "data")
        assert {kind for kind, _ in stored} == {"blob"}
        assert sum(size for _, size in stored) * 3 < len(json.dumps(rows).encode())
        assert backend.read_source(FILE) == rows

    def test_a_repeat_chain_is_found_in_compressed_rows(self, backend):
        backend.write_source(
            FILE, [_source(1), _source(2, repeat_of_source_guid="guid-1"), _source(3)]
        )
        backend.connection.execute(
            "INSERT INTO source_data (relative_path, source_guid, data) VALUES (?, 'guid-8', ?)",
            (FILE, json.dumps(_source(8, repeat_of_source_guid="guid-3"))),
        )
        backend.connection.commit()

        assert backend.records_share_a_repeat_chain(["guid-1"]) is True
        assert backend.records_share_a_repeat_chain(["guid-2"]) is True
        assert backend.records_share_a_repeat_chain(["guid-3"]) is True
        assert backend.records_share_a_repeat_chain(["guid-8"]) is True
        assert backend.records_share_a_repeat_chain(["guid-0"]) is False

    def test_clearing_source_data_and_writing_again_reads_back_elsewhere(self, backend, db):
        backend.write_source(FILE, [_source(1)])
        backend.clear_source_data()
        backend.write_source(FILE, [{"source_guid": "guid-9", "content": {"other": "words"}}])

        reader = _fresh_reader(db)
        try:
            assert reader.read_source(FILE) == [
                {"source_guid": "guid-9", "content": {"other": "words"}}
            ]
        finally:
            reader.close()


class TestCheckpoints:
    def test_rows_are_stored_smaller_and_read_back(self, backend, db):
        rows = _records(3)
        backend.save_checkpoint_records(ACTION, FILE, rows)

        stored = _stored(backend, "checkpoint_output", "record_data")
        assert {kind for kind, _ in stored} == {"blob"}
        assert sum(size for _, size in stored) * 3 < len(json.dumps(rows).encode())
        assert backend.read_checkpoint_records(ACTION, FILE) == rows
        assert backend.checkpointed_without_row_count(ACTION, FILE) == set()

        reader = _fresh_reader(db)
        try:
            assert reader.read_checkpoint_records(ACTION, FILE) == rows
        finally:
            reader.close()

    def test_a_row_an_earlier_version_stored_as_one_record_is_still_named(self, backend):
        backend.save_checkpoint_records(ACTION, FILE, _records(1))
        backend.connection.execute(
            "INSERT INTO checkpoint_output (action_name, relative_path, source_guid, record_data)"
            " VALUES (?, ?, 'guid-5', ?)",
            (ACTION, FILE, json.dumps(_record(5))),
        )
        backend.connection.commit()

        assert backend.checkpointed_without_row_count(ACTION, FILE) == {"guid-5"}
        assert _summaries(backend.read_checkpoint_records(ACTION, FILE)) == _summaries(
            [_record(0), _record(5)]
        )

    def test_clearing_an_action_and_checkpointing_again_reads_back_elsewhere(self, backend, db):
        backend.save_checkpoint_records(ACTION, FILE, _records(2))
        backend.clear_checkpoint_records(ACTION)
        backend.save_checkpoint_records(ACTION, FILE, [_record(4)])

        reader = _fresh_reader(db)
        try:
            assert _summaries(reader.read_checkpoint_records(ACTION, FILE)) == _summaries(
                [_record(4)]
            )
        finally:
            reader.close()


class TestDispositionSnapshots:
    SNAPSHOT = json.dumps({"source_guid": "guid-1", "content": {"page_content": BODY}})

    def test_a_snapshot_is_stored_smaller_and_read_back(self, backend, db):
        backend.set_disposition(
            ACTION,
            "guid-1",
            "failed",
            reason="boom",
            relative_path=FILE,
            input_snapshot=self.SNAPSHOT,
        )
        backend.set_dispositions_batch(
            [(ACTION, "guid-2", "exhausted", "worn out", FILE, self.SNAPSHOT, None)]
        )
        backend.set_disposition(ACTION, "guid-3", "success", relative_path=FILE)

        stored = _stored(backend, "record_disposition", "input_snapshot")
        assert [kind for kind, _ in stored] == ["blob", "blob", "null"]
        assert stored[0][1] * 3 < len(self.SNAPSHOT.encode())
        rows = {r["record_id"]: r for r in backend.get_disposition(ACTION)}
        assert rows["guid-1"]["input_snapshot"] == self.SNAPSHOT
        assert rows["guid-2"]["input_snapshot"] == self.SNAPSHOT
        assert rows["guid-3"]["input_snapshot"] is None

        reader = _fresh_reader(db)
        try:
            found = reader.get_disposition(ACTION, record_id="guid-1")[0]
        finally:
            reader.close()
        assert found["input_snapshot"] == self.SNAPSHOT

    def test_a_snapshot_over_the_cap_is_still_the_truncated_marker(self, backend):
        huge = json.dumps({"content": "x" * 20_000})
        backend.set_disposition(ACTION, "guid-1", "failed", input_snapshot=huge)

        marker = json.loads(backend.get_disposition(ACTION)[0]["input_snapshot"])
        assert marker["__truncated__"] is True
        assert marker["partial"] == huge[:8192]

    def test_a_snapshot_stored_as_text_still_reads_back(self, backend):
        backend.connection.execute(
            "INSERT INTO record_disposition (action_name, record_id, disposition, input_snapshot)"
            " VALUES (?, 'guid-old', 'failed', ?)",
            (ACTION, self.SNAPSHOT),
        )
        backend.connection.commit()
        backend.set_disposition(ACTION, "guid-new", "failed", input_snapshot=self.SNAPSHOT)

        rows = {r["record_id"]: r for r in backend.get_disposition(ACTION)}
        assert rows["guid-old"]["input_snapshot"] == self.SNAPSHOT
        assert rows["guid-new"]["input_snapshot"] == self.SNAPSHOT

    def test_clearing_an_action_and_writing_again_reads_back_elsewhere(self, backend, db):
        backend.set_disposition(ACTION, "guid-1", "failed", input_snapshot=self.SNAPSHOT)
        backend.clear_disposition(ACTION)
        other = json.dumps({"content": {"page_content": "different words " * 50}})
        backend.set_disposition(ACTION, "guid-2", "failed", input_snapshot=other)

        reader = _fresh_reader(db)
        try:
            assert reader.get_disposition(ACTION)[0]["input_snapshot"] == other
        finally:
            reader.close()

    def test_a_corrupt_snapshot_is_an_error_naming_the_record(self, backend):
        backend.set_disposition(ACTION, "guid-1", "failed", input_snapshot=self.SNAPSHOT)
        backend.connection.execute(
            "UPDATE record_disposition SET input_snapshot = ?",
            (b"\x00\x00\x00\x00not a zlib stream",),
        )
        backend.connection.commit()

        with pytest.raises(SerializationError, match=rf"record_disposition.*{ACTION}.*guid-1"):
            backend.get_disposition(ACTION)
