"""Each checkpoint row holds the list of rows its record answered with.

A row that decodes to anything else is a writer bug or a damaged file. Resume
must not read it as rows, so reading it is an error that names the row.
"""

import json

import pytest

from agent_actions.errors.processing import SerializationError
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    store.initialize()
    yield store
    store.close()


def test_a_row_holding_one_record_object_is_refused(backend):
    cursor = backend.connection.cursor()
    cursor.execute(
        "INSERT INTO checkpoint_output (action_name, relative_path, source_guid, record_data)"
        " VALUES (?, ?, ?, ?)",
        (
            "act",
            "f.json",
            "g1",
            backend._compress(
                cursor, "act", backend._CHECKPOINT_DATA, json.dumps({"source_guid": "g1"})
            ),
        ),
    )
    backend.connection.commit()

    with pytest.raises(SerializationError, match="record 'g1'"):
        backend.read_checkpoint_records("act", "f.json")


def test_a_row_holding_a_list_reads_back(backend):
    backend.save_checkpoint_records("act", "f.json", [{"source_guid": "g1", "x": 1}])

    assert backend.read_checkpoint_records("act", "f.json") == [{"source_guid": "g1", "x": 1}]
