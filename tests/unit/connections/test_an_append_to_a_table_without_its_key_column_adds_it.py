"""An append to a table that lacks a key column adds the column, as a merge does.

The keys the table held were read with a select naming the missing column, so
the write crashed with the driver's own error instead of adding it.
"""

import pytest

from agent_actions.connections import WriteMode
from agent_actions.connections.sqlite import SqliteConnector
from agent_actions.errors import ConfigurationError


@pytest.fixture
def connector(tmp_path):
    with SqliteConnector(tmp_path / "warehouse.db") as connector:
        connector._open().execute("CREATE TABLE tickets_out (id INTEGER, summary TEXT)")
        yield connector


@pytest.mark.parametrize("mode", [WriteMode.APPEND, WriteMode.MERGE])
def test_the_missing_key_column_is_added_and_the_rows_written(connector, mode):
    rows = [("g1", 1, "short"), ("g2", 2, "long")]

    written = connector.write(
        "tickets_out", ["source_guid", "id", "summary"], rows, mode=mode, key=["source_guid"]
    )

    assert written == 2
    held = list(connector.read("SELECT source_guid, id FROM tickets_out ORDER BY id"))
    assert held == [{"source_guid": "g1", "id": 1}, {"source_guid": "g2", "id": 2}]


def test_a_table_without_the_key_column_holds_no_keys(connector):
    assert connector.held_keys("tickets_out", ["source_guid"]) == set()


def test_keys_that_cannot_be_read_are_refused_as_a_configuration_error(connector, monkeypatch):
    def broken(query):
        raise RuntimeError("disk I/O error")
        yield

    monkeypatch.setattr(connector, "_read_tuples", broken)

    with pytest.raises(ConfigurationError, match="Cannot read the keys tickets_out holds"):
        connector.held_keys("tickets_out", ["id"])
