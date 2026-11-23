"""records_share_a_repeat_chain answers from source_data.repeat_of_source_guid (1586).

A compressed row cannot be read by SQLite's JSON functions, so the backend
stores the guid a row repeats in its own indexed column. NULL there means the
row was written before the column existed, and its payload is read instead.
"""

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

FILE = "pages.json"
BODY = "the quick brown fox jumps over the lazy dog. " * 20


def _source(guid: str, repeat_of: object = None) -> dict:
    row: dict = {"source_guid": guid, "content": {"page_content": BODY}}
    if repeat_of is not None:
        row["repeat_of_source_guid"] = repeat_of
    return row


def _open(db) -> SQLiteBackend:
    backend = SQLiteBackend(str(db), workflow_name="wf")
    backend.initialize()
    return backend


@pytest.fixture
def db(tmp_path):
    return tmp_path / "wf.db"


@pytest.fixture
def backend(db):
    b = _open(db)
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


def _forget_column(backend) -> None:
    """Make every row read as one written before the column existed."""
    backend.connection.execute("UPDATE source_data SET repeat_of_source_guid = NULL")
    backend.connection.commit()


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

    def test_a_value_the_column_cannot_hold_is_left_to_the_payload(self, backend):
        backend.write_source(FILE, [_source("odd", repeat_of=7), _source("blank", repeat_of="")])

        stored = dict(
            backend.connection.execute(
                "SELECT source_guid, repeat_of_source_guid FROM source_data"
            ).fetchall()
        )

        assert stored == {"odd": None, "blank": None}
        assert backend.records_share_a_repeat_chain(["odd"]) is True
        assert backend.records_share_a_repeat_chain(["blank"]) is True

    def test_the_column_is_indexed(self, backend):
        indexed = {
            row[2]
            for (name,) in backend.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'source_data'"
            ).fetchall()
            for row in backend.connection.execute(f"PRAGMA index_info({name})").fetchall()
        }

        assert "repeat_of_source_guid" in indexed


class TestBothDirections:
    def test_rows_written_with_the_column(self, backend):
        _write_chain(backend)

        _assert_chain_answers(backend)

    def test_compressed_rows_written_before_the_column(self, backend):
        _write_chain(backend)
        _forget_column(backend)

        _assert_chain_answers(backend)

    def test_a_legacy_original_repeated_by_a_new_row(self, backend):
        backend.write_source("a.json", [_source("base"), _source("solo")])
        _forget_column(backend)
        backend.write_source("b.json", [_source("repeat", repeat_of="base")])

        _assert_chain_answers(backend)

    def test_a_legacy_repeat_of_a_new_original(self, backend):
        backend.write_source("b.json", [_source("repeat", repeat_of="base")])
        _forget_column(backend)
        backend.write_source("a.json", [_source("base"), _source("solo")])

        _assert_chain_answers(backend)


class TestCost:
    def test_rows_written_with_the_column_are_not_decoded(self, backend, decodes):
        _write_chain(backend)

        _assert_chain_answers(backend)

        assert decodes == []

    def test_rows_written_before_the_column_are_decoded(self, backend, decodes):
        _write_chain(backend)
        _forget_column(backend)

        assert backend.records_share_a_repeat_chain(["solo"]) is False

        assert len(decodes) == 3

    def test_only_rows_written_before_the_column_are_decoded(self, backend, decodes):
        backend.write_source("a.json", [_source("old")])
        _forget_column(backend)
        _write_chain(backend)

        assert backend.records_share_a_repeat_chain(["solo"]) is False

        assert decodes == ["record 'old'"]
