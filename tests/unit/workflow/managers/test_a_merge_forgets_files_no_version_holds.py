"""A version merge deletes what it stores for a file no version source holds (1258).

The merge walks its own stored files as input, the ones the correlator just wrote
among them. Once a version source no longer holds a file, because its input was
removed, nothing correlates it, and the merge's own rows for it were walked and
sent on as though they were its input.
"""

import json
import logging
import sqlite3

import pytest

from agent_actions.storage.backend import batch_file_names_key
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers import loop
from agent_actions.workflow.managers.loop import VersionOutputCorrelator

LIFECYCLE = {"_state": "processed", "_state_schema_version": 1, "_delta_mode": "full"}
SOURCES = ["scorer_1", "scorer_2"]
MERGE = "consumer"


@pytest.fixture
def agent_folder(tmp_path):
    return tmp_path / "wf" / "agent_io"


@pytest.fixture
def backend(agent_folder):
    b = SQLiteBackend.create(db_path=str(agent_folder / "store" / "test.db"), workflow_name="test")
    b.initialize()
    yield b
    b.close()


def _version(name):
    return {
        "source_guid": "sg-001",
        "version_correlation_id": "vc-001",
        "target_id": f"tid-{name}",
        "node_id": f"{name}_n",
        "lineage": [f"{name}_n"],
        "content": {name: {"score": 1}},
        **LIFECYCLE,
    }


def _versions_hold(backend, *files):
    for source in SOURCES:
        for path in files:
            backend._write_target_raw(source, path, [_version(source)])


def _merge_holds(backend, *files):
    for path in files:
        backend._write_target_raw(MERGE, path, [{"source_guid": path, **LIFECYCLE}])


def _correlate(agent_folder, backend):
    VersionOutputCorrelator(agent_folder, storage_backend=backend).prepare_correlated_input(
        MERGE, SOURCES, 2
    )


def test_a_file_no_version_holds_goes_and_the_correlated_one_stays(agent_folder, backend):
    _versions_hold(backend, "pages.json")
    _merge_holds(backend, "gone.json", "pages.json")

    _correlate(agent_folder, backend)

    assert backend.list_target_files(MERGE) == ["pages.json"]


def test_a_file_one_version_still_holds_stays(agent_folder, backend):
    """Its rows there may all be filtered; it is still input, not gone."""
    _versions_hold(backend, "pages.json")
    backend._write_target_raw(SOURCES[0], "quiet.json", [])
    _merge_holds(backend, "pages.json", "quiet.json")

    _correlate(agent_folder, backend)

    assert backend.list_target_files(MERGE) == ["pages.json", "quiet.json"]


def test_the_name_recorded_for_it_is_forgotten(agent_folder, backend):
    _versions_hold(backend, "sub/pages.json")
    _merge_holds(backend, "sub/gone.json", "sub/pages.json")
    backend.save_metadata(
        batch_file_names_key(MERGE),
        json.dumps({"sub/gone.json": "sub/gone.json", "sub/pages.json": "sub/pages.json"}),
    )

    _correlate(agent_folder, backend)

    assert json.loads(backend.load_metadata(batch_file_names_key(MERGE))) == {
        "sub/pages.json": "sub/pages.json"
    }


def test_a_delete_that_fails_only_warns(agent_folder, backend, monkeypatch, caplog):
    _versions_hold(backend, "pages.json")
    _merge_holds(backend, "gone.json", "pages.json")

    def refuse(*_args):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(backend, "delete_target_files", refuse)
    with caplog.at_level(logging.WARNING, logger=loop.__name__):
        _correlate(agent_folder, backend)

    assert backend.list_target_files(MERGE) == ["gone.json", "pages.json"]
    assert "database is locked" in caplog.text
