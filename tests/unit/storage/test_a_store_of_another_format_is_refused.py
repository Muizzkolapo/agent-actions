"""A store opens only when it records the storage format this version writes.

Any other store, older, newer or with no recorded format, is refused before
anything reads or writes it, and the refusal names the file and the command that
removes it.
"""

import sqlite3

import pytest

from agent_actions.errors.configuration import ConfigurationError
from agent_actions.storage.backend import StorageBackend
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

CURRENT = str(StorageBackend._STORAGE_FORMAT_VERSION)


def _store(tmp_path):
    return tmp_path / "agent_io" / "store" / "wf.db"


def _create(db_path):
    backend = SQLiteBackend(str(db_path), "wf")
    backend.initialize()
    backend.close()


def _set_version(db_path, version):
    conn = sqlite3.connect(db_path)
    if version is None:
        conn.execute("DELETE FROM workflow_metadata WHERE key = 'storage_format_version'")
    else:
        conn.execute(
            "UPDATE workflow_metadata SET value = ? WHERE key = 'storage_format_version'",
            (version,),
        )
    conn.commit()
    conn.close()


def _stored_version(db_path):
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT value FROM workflow_metadata WHERE key = 'storage_format_version'"
    ).fetchone()
    conn.close()
    return None if row is None else row[0]


def test_the_format_is_at_least_four():
    assert StorageBackend._STORAGE_FORMAT_VERSION >= 4


def test_a_new_store_records_the_current_format_and_opens_again(tmp_path):
    db_path = _store(tmp_path)
    _create(db_path)

    assert _stored_version(db_path) == CURRENT

    backend = SQLiteBackend(str(db_path), "wf")
    backend.initialize()
    backend.write_source("in.json", [{"source_guid": "g1", "content": {}}])
    assert backend.read_source("in.json")[0]["source_guid"] == "g1"
    backend.close()

    readonly = SQLiteBackend.create_readonly(db_path)
    assert readonly.list_source_files() == ["in.json"]
    readonly.close()


@pytest.mark.parametrize("version", ["3", "1", None, str(int(CURRENT) + 1), "x"])
def test_a_store_of_another_format_is_refused_with_the_clean_hint(tmp_path, version):
    db_path = _store(tmp_path)
    _create(db_path)
    _set_version(db_path, version)

    backend = SQLiteBackend(str(db_path), "wf")
    with pytest.raises(ConfigurationError) as refused:
        backend.initialize()

    message = str(refused.value)
    assert str(db_path) in message
    assert "agac clean -a wf --all" in message
    assert backend._connection is None
    assert _stored_version(db_path) == version


@pytest.mark.parametrize("version", ["3", None])
def test_a_read_only_open_refuses_it_too(tmp_path, version):
    db_path = _store(tmp_path)
    _create(db_path)
    _set_version(db_path, version)

    with pytest.raises(ConfigurationError, match="agac clean -a wf --all"):
        SQLiteBackend.create_readonly(db_path)


def test_a_store_without_the_metadata_table_is_refused(tmp_path):
    db_path = _store(tmp_path)
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE target_data (id INTEGER PRIMARY KEY, data TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(ConfigurationError, match="agac clean -a wf --all"):
        SQLiteBackend(str(db_path), "wf").initialize()

    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert tables == {"target_data"}
