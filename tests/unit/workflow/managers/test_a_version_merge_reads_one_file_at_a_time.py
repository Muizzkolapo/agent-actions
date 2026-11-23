"""A version merge holds the version files of one entry at a time.

The correlator read every file of every version whole before the merge's walk began, and
the walk kept the merged input of every file for its whole length, with each version file
in the store's cache (#1865). Correlation pairs rows within one file, so each file is now
read and correlated once to check it and let go, then read and correlated again when the
walk processes it, and let go before the next.
"""

import gc
import tracemalloc
import weakref
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import DataValidationError
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.managers.loop import VersionOutputCorrelator
from agent_actions.workflow.runner_file_processing import process_from_storage_backend

LIFECYCLE = {"_state": "processed", "_state_schema_version": 1, "_delta_mode": "full"}
SOURCES = ["scorer_1", "scorer_2"]
MERGE = "consumer"
FILES = [f"f{index}.json" for index in range(4)]


@pytest.fixture
def agent_folder(tmp_path):
    return tmp_path / "wf" / "agent_io"


@pytest.fixture
def backend(agent_folder):
    store = SQLiteBackend.create(
        db_path=str(agent_folder / "store" / "test.db"), workflow_name="test"
    )
    store.initialize()
    yield store
    store.close()


def _version(source: str, guid: str, **content: Any) -> dict[str, Any]:
    return {
        "source_guid": guid,
        "version_correlation_id": f"vc-{guid}",
        "content": {source: {"score": 1, **content}},
        **LIFECYCLE,
    }


def _versions_hold(backend: SQLiteBackend, files: dict[str, dict[str, list[str]]], **content):
    """*files* maps each file to the record ids each version holds there."""
    for path, held in files.items():
        for source, guids in held.items():
            backend._write_target_raw(
                source, path, [_version(source, guid, **content) for guid in guids]
            )
    backend._reconstruction_cache.clear()


def _two_records_each() -> dict[str, dict[str, list[str]]]:
    return {path: {source: [f"{path}-a", f"{path}-b"] for source in SOURCES} for path in FILES}


def _correlate(agent_folder: Path, backend: SQLiteBackend):
    return VersionOutputCorrelator(agent_folder, storage_backend=backend).prepare_correlated_input(
        MERGE, SOURCES, 2
    )


def _versions_cached(backend: SQLiteBackend) -> set[tuple[str, str]]:
    return {key for key in backend._reconstruction_cache if key[0] in SOURCES}


def test_correlating_leaves_no_version_file_in_the_store_cache(agent_folder, backend):
    _versions_hold(backend, _two_records_each())

    correlated = _correlate(agent_folder, backend)

    assert sorted(correlated) == FILES
    assert _versions_cached(backend) == set()


def test_the_correlated_input_holds_no_rows_once_it_is_returned(agent_folder, backend):
    _versions_hold(backend, _two_records_each(), text="x" * 50_000)
    # Fills what the store keeps once per process, such as its compression dictionary.
    _correlate(agent_folder, backend)
    backend._reconstruction_cache.clear()
    gc.collect()
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        correlated = _correlate(agent_folder, backend)
        gc.collect()
        held = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()

    # Every file of both versions is 800 KB of text; one row of one version is 50 KB.
    assert sorted(correlated) == FILES
    assert held < 50_000


def _walk(tmp_path: Path, backend: SQLiteBackend, correlated, per_file):
    target = tmp_path / "agent_io" / "target" / MERGE
    target.mkdir(parents=True, exist_ok=True)
    params = MagicMock()
    params.action_config = {}
    params.action_name = MERGE
    params.output_directory = str(tmp_path / "output")
    params.upstream_data_dirs = [str(target)]
    params.correlated_input = correlated
    runner = MagicMock()
    runner.retried_records = frozenset()
    runner.storage_backend = backend
    runner.action_configs = {}
    runner._process_single_file = per_file
    return process_from_storage_backend(runner, params)


def test_the_walk_holds_only_the_merged_rows_of_the_entry_it_processes(
    tmp_path, agent_folder, backend
):
    _versions_hold(backend, _two_records_each())
    correlated = _correlate(agent_folder, backend)
    seen: list[tuple[list[str], set[tuple[str, str]]]] = []

    def prepares_without_writing(file_params):
        guids = [row["source_guid"] for row in file_params.data]
        seen.append((guids, _versions_cached(backend)))

    found, processed, errors = _walk(tmp_path, backend, correlated, prepares_without_writing)

    assert (found, processed, errors.messages) == (4, 4, [])
    assert seen == [([f"{path}-a", f"{path}-b"], set()) for path in FILES]
    assert _versions_cached(backend) == set()


def test_each_file_correlates_to_the_rows_it_did_when_every_file_was_held(agent_folder, backend):
    _versions_hold(
        backend,
        {
            "both.json": {"scorer_1": ["g1", "g2"], "scorer_2": ["g2", "g1"]},
            "short.json": {"scorer_1": ["g3", "g4"], "scorer_2": ["g3"]},
            "one.json": {"scorer_1": ["g5"]},
            "empty.json": {"scorer_1": [], "scorer_2": []},
        },
    )
    # Held empty by a version that holds rows in another file.
    backend._write_target_raw("scorer_2", "quiet.json", [])
    backend._reconstruction_cache.clear()

    correlated = _correlate(agent_folder, backend)

    assert {
        path: [(row["source_guid"], sorted(row["content"])) for row in correlated[path]]
        for path in correlated
    } == {
        "both.json": [("g1", SOURCES), ("g2", SOURCES)],
        "short.json": [("g3", SOURCES), ("g4", ["scorer_1"])],
        "one.json": [("g5", ["scorer_1"])],
        "empty.json": [],
        "quiet.json": [],
    }


def test_a_file_listed_only_by_a_version_that_holds_no_row_anywhere_is_left_out(
    agent_folder, backend
):
    _versions_hold(
        backend,
        {"pages.json": {"scorer_1": ["g1"], "scorer_2": []}, "nobody.json": {"scorer_2": []}},
    )

    correlated = _correlate(agent_folder, backend)

    assert sorted(correlated) == ["pages.json"]
    assert "nobody.json" not in correlated
    assert [row["source_guid"] for row in correlated["pages.json"]] == ["g1"]


def test_a_record_that_cannot_be_aligned_in_the_last_file_stops_the_merge_up_front(
    agent_folder, backend
):
    _versions_hold(backend, _two_records_each())
    unaligned = _version("scorer_1", "bad")
    del unaligned["version_correlation_id"]
    backend._write_target_raw("scorer_1", "z_last.json", [unaligned])
    backend._reconstruction_cache.clear()

    with pytest.raises(DataValidationError):
        _correlate(agent_folder, backend)

    assert _versions_cached(backend) == set()


class _Rows(list):
    """A version file's rows; a list subclass so the test can hold it weakly."""


class _WatchingBackend:
    """Notes, at each read, which earlier reads are still alive."""

    def __init__(self, files: dict[str, dict[str, list[dict[str, Any]]]]):
        self._files = files
        self._read: dict[str, weakref.ref] = {}
        self.alive_at_read: list[tuple[str, list[str]]] = []

    def list_target_files(self, version: str) -> list[str]:
        return list(self._files.get(version, {}))

    def read_target(self, version: str, path: str) -> _Rows:
        gc.collect()
        alive = sorted(name for name, ref in self._read.items() if ref() is not None)
        self.alive_at_read.append((f"{version}/{path}", alive))
        rows = _Rows(dict(row) for row in self._files[version][path])
        self._read[f"{version}/{path}"] = weakref.ref(rows)
        return rows

    def forget_reconstructed(self, version: str, path: str) -> None:
        pass


def test_a_file_is_let_go_before_the_next_is_read(tmp_path):
    backend = _WatchingBackend(
        {
            source: {path: [_version(source, f"{path}-a")] for path in ("a.json", "b.json")}
            for source in SOURCES
        }
    )
    correlator = VersionOutputCorrelator(tmp_path, storage_backend=backend)
    correlator._forget_files_no_version_holds = lambda *args: None  # type: ignore[method-assign]

    correlated = correlator.prepare_correlated_input(MERGE, SOURCES, 2)
    checked = backend.alive_at_read
    backend.alive_at_read = []
    for path in correlated:
        rows = correlated[path]
        assert [row["source_guid"] for row in rows] == [f"{path}-a"]
        del rows

    expected = [
        ("scorer_1/a.json", []),
        ("scorer_2/a.json", ["scorer_1/a.json"]),
        ("scorer_1/b.json", []),
        ("scorer_2/b.json", ["scorer_1/b.json"]),
    ]
    assert checked == expected
    assert backend.alive_at_read == expected
