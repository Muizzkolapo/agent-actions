"""A version merge holds the version files of one entry at a time.

The correlator read every file of every version whole before the merge's walk began, and
the walk kept the merged input of every file for its whole length, with each version file
in the store's cache (#1865). Correlation pairs rows within one file, so each file is now
read and correlated once to check it and let go, then read and correlated again when the
walk processes it, and let go before the next.
"""

import gc
import logging
import tracemalloc
import weakref
from collections import Counter
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


class _Marker:
    """Put in a version row's own namespace, which a merged row shares, to hold it weakly."""


def _marking_reads(backend: SQLiteBackend, monkeypatch) -> dict[str, list[weakref.ref]]:
    """Mark each version row a read returns; at each read, assert no other file's mark lives."""
    read = backend.read_target
    marks: dict[str, list[weakref.ref]] = {}

    def marking_read(version: str, path: str):
        gc.collect()
        alive = sorted(
            other
            for other, refs in marks.items()
            if other != path and any(ref() is not None for ref in refs)
        )
        assert alive == [], f"rows of {alive} still held when {version}/{path} is read"
        rows = read(version, path)
        if version in SOURCES:
            for row in rows:
                mark = _Marker()
                row["content"][version]["mark"] = mark
                marks.setdefault(path, []).append(weakref.ref(mark))
        return rows

    monkeypatch.setattr(backend, "read_target", marking_read)
    return marks


def test_the_walk_lets_an_entry_s_merged_rows_go_before_it_looks_up_the_next(
    tmp_path, agent_folder, backend, monkeypatch
):
    _versions_hold(backend, _two_records_each())
    correlated = _correlate(agent_folder, backend)
    marks = _marking_reads(backend, monkeypatch)
    held: list[int] = []

    def prepares_without_writing(file_params):
        held.append(
            sum(
                isinstance(row["content"][SOURCES[0]].get("mark"), _Marker)
                for row in file_params.data
            )
        )

    found, processed, errors = _walk(tmp_path, backend, correlated, prepares_without_writing)

    assert (found, processed, errors.messages) == (4, 4, [])
    # The merged rows the walk processes hold the marks, so a mark that lives holds them.
    assert held == [2] * len(FILES)
    gc.collect()
    assert sorted(marks) == FILES
    assert [ref for refs in marks.values() for ref in refs if ref() is not None] == []


def test_the_walk_reads_again_only_the_versions_the_check_kept_for_a_file(
    tmp_path, agent_folder, backend, monkeypatch
):
    versions = [*SOURCES, "scorer_3"]
    _versions_hold(
        backend,
        {
            "a.json": {"scorer_1": ["a1"], "scorer_2": ["a1"], "scorer_3": []},
            # scorer_2 does not list b.json.
            "b.json": {"scorer_1": ["b1"], "scorer_3": []},
            # Held empty by scorer_2, which holds a row in a.json.
            "d.json": {"scorer_1": ["d1"], "scorer_2": []},
            # Listed only by scorer_3, which holds no row anywhere.
            "e.json": {"scorer_3": []},
        },
    )
    correlated = VersionOutputCorrelator(
        agent_folder, storage_backend=backend
    ).prepare_correlated_input(MERGE, versions, 2)
    read = backend.read_target
    reads: Counter[tuple[str, str]] = Counter()

    def counting_read(version: str, path: str):
        if version in versions:
            reads[(version, path)] += 1
        return read(version, path)

    monkeypatch.setattr(backend, "read_target", counting_read)

    found, processed, errors = _walk(tmp_path, backend, correlated, lambda file_params: None)

    assert (found, processed, errors.messages) == (3, 3, [])
    assert reads == Counter(
        {
            ("scorer_1", "a.json"): 1,
            ("scorer_2", "a.json"): 1,
            ("scorer_1", "b.json"): 1,
            ("scorer_1", "d.json"): 1,
            ("scorer_2", "d.json"): 1,
        }
    )


def test_a_record_a_version_folded_away_is_warned_of_once(agent_folder, backend, caplog):
    folding = _version("scorer_1", "g1")
    folding["folded_sources"] = {"g2": "scorer_1"}
    backend._write_target_raw("scorer_1", "items.json", [folding])
    backend._write_target_raw(
        "scorer_2", "items.json", [_version("scorer_2", "g1"), _version("scorer_2", "g2")]
    )
    backend._reconstruction_cache.clear()

    with caplog.at_level(logging.WARNING, logger="agent_actions.workflow.managers.loop"):
        correlated = _correlate(agent_folder, backend)
        first = correlated["items.json"]
        again = correlated["items.json"]

    warned = [
        record.getMessage()
        for record in caplog.records
        if "consumed into another record's output" in record.getMessage()
    ]
    assert len(warned) == 1
    assert warned[0].startswith("Version merge: record g2 ")
    # Each lookup still leaves the record unprocessed; only the warning is not repeated.
    for rows in (first, again):
        assert {
            row["source_guid"]: row["metadata"].get("upstream_reason")
            for row in rows
            if row["_state"] == "cascade_skipped"
        } == {"g2": "consumed_into_output"}
