"""records_share_a_repeat_chain answers from source_data.repeat_of_source_guid (1586).

A compressed row cannot be read by SQLite's JSON functions, so the backend
stores the guid a row repeats in its own indexed column, and an empty string
for a row that repeats nothing. The column is never NULL.
"""

import sqlite3

import pytest

from agent_actions.errors.validation import DataValidationError
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

FILE = "pages.json"
BODY = "the quick brown fox jumps over the lazy dog. " * 20


def _source(guid: str, repeat_of: object = None) -> dict:
    row: dict = {"source_guid": guid, "content": {"page_content": BODY}}
    if repeat_of is not None:
        row["repeat_of_source_guid"] = repeat_of
    return row


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "wf.db"), workflow_name="wf")
    b.initialize()
    yield b
    b.close()


@pytest.fixture
def decodes(backend, monkeypatch):
    calls: list[str] = []
    original = backend.decode_payload

    def counting(value, *, table, where):
        calls.append(where)
        return original(value, table=table, where=where)

    monkeypatch.setattr(backend, "decode_payload", counting)
    return calls


def _write_chain(backend) -> None:
    backend.write_source("a.json", [_source("base"), _source("solo")])
    backend.write_source("b.json", [_source("repeat", repeat_of="base")])


def _assert_chain_answers(backend) -> None:
    assert backend.records_share_a_repeat_chain(["repeat"]) is True
    assert backend.records_share_a_repeat_chain(["base"]) is True
    assert backend.records_share_a_repeat_chain(["solo", "repeat"]) is True
    assert backend.records_share_a_repeat_chain(["solo"]) is False
    assert backend.records_share_a_repeat_chain(["nonexistent"]) is False


class TestTheColumn:
    def test_write_source_stores_the_repeated_guid_and_empty_for_an_original(self, backend):
        _write_chain(backend)

        stored = dict(
            backend.connection.execute(
                "SELECT source_guid, repeat_of_source_guid FROM source_data"
            ).fetchall()
        )

        assert stored == {"base": "", "solo": "", "repeat": "base"}

    def test_a_replacing_write_replaces_the_column(self, backend):
        backend.write_source(FILE, [_source("x", repeat_of="base")])
        backend.write_source(FILE, [_source("x")], enable_deduplication=False)

        assert backend.records_share_a_repeat_chain(["x"]) is False
        assert backend.records_share_a_repeat_chain(["base"]) is False

    @pytest.mark.parametrize("repeat_of", [7, ""])
    def test_a_value_the_column_cannot_hold_is_refused(self, backend, repeat_of):
        with pytest.raises(DataValidationError, match="repeat_of_source_guid"):
            backend.write_source(FILE, [_source("good"), _source("odd", repeat_of=repeat_of)])

        assert backend.connection.execute("SELECT COUNT(*) FROM source_data").fetchone()[0] == 0

    def test_the_store_refuses_a_null_column(self, backend):
        with pytest.raises(sqlite3.IntegrityError, match="repeat_of_source_guid"):
            backend.connection.execute(
                "INSERT INTO source_data (relative_path, source_guid, data, repeat_of_source_guid)"
                " VALUES (?, 'g', x'00', NULL)",
                (FILE,),
            )

    def test_the_column_is_indexed(self, backend):
        indexed = {
            row[2]
            for (name,) in backend.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'source_data'"
            ).fetchall()
            for row in backend.connection.execute(f"PRAGMA index_info({name})").fetchall()
        }

        assert "repeat_of_source_guid" in indexed


def test_both_directions_are_answered_without_decoding_a_row(backend, decodes):
    _write_chain(backend)

    _assert_chain_answers(backend)

    assert decodes == []
