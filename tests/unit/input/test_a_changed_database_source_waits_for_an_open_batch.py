"""A database source whose query changed is not read again while its action's batch is open.

Reading it removed the snapshot the batch was sent from, so the answers on their
way no longer matched the staged rows. `--refresh-input` already waited; a
changed sql, file count or connection setting did not.
"""

import sqlite3

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.input.loaders.data_source import resolve_start_node_data_source


@pytest.fixture
def project(tmp_path):
    with sqlite3.connect(tmp_path / "w.db") as raw:
        raw.execute("CREATE TABLE tickets (id INTEGER, title TEXT)")
        raw.executemany("INSERT INTO tickets VALUES (?, ?)", [(1, "a"), (2, "b")])
    (tmp_path / "agent_actions.yml").write_text(
        "connections:\n  warehouse:\n    type: sqlite\n    path: w.db\n"
    )
    io_dir = tmp_path / "agent_io"
    io_dir.mkdir()
    return tmp_path, io_dir


def _source(sql: str) -> dict:
    return {"type": "database", "connection": "warehouse", "sql": sql}


def _resolve(project, sql: str, open_batch: bool):
    root, io_dir = project
    return resolve_start_node_data_source(
        io_dir, _source(sql), "classify", root, has_open_batch=lambda action: open_batch
    )


def test_a_changed_query_under_an_open_batch_is_refused_and_the_snapshot_kept(project):
    first = _resolve(project, "SELECT id, title FROM tickets", open_batch=False)

    with pytest.raises(ConfigurationError, match="a batch is still open for it"):
        _resolve(project, "SELECT id, title FROM tickets WHERE id = 1", open_batch=True)

    assert all(directory.exists() for directory in first.directories)


def test_the_unchanged_query_is_read_from_its_snapshot_under_an_open_batch(project):
    first = _resolve(project, "SELECT id, title FROM tickets", open_batch=False)

    again = _resolve(project, "SELECT id, title FROM tickets", open_batch=True)

    assert again.directories == first.directories


def test_with_no_batch_open_a_changed_query_is_read(project):
    _resolve(project, "SELECT id, title FROM tickets", open_batch=False)

    changed = _resolve(project, "SELECT id FROM tickets", open_batch=False)

    assert all(directory.exists() for directory in changed.directories)


def test_a_first_read_needs_no_batch_check(project):
    root, io_dir = project

    def never(action):
        raise AssertionError("asked about a batch before any snapshot existed")

    resolve_start_node_data_source(
        io_dir, _source("SELECT id FROM tickets"), "classify", root, has_open_batch=never
    )
