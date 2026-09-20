"""A file lost from the walk must make the action's record count unknown (625).

610 made a completed action's stamp carry what the run processed, so a later
limit at or above that count can be shown to leave the record set whole. The
count is summed only from chunks that reach the slice — but a file can be lost
before its slice and the action still completes, because a per-file failure is
never inferred to be fatal to the action. Those records are never counted, the
stamp still says ``truncated: False``, and a later limit below the true total
reads as one that could not have bitten. The action is skipped and its short
output is vouched for, which is the direction 610 exists to exclude.

There are three walkers and five ways to lose a file between them, so each is
covered here: losing one is enough to under-count, and an under-count is the
only error that reads as "a smaller limit is safe".
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.utils.limits import record_indices_to_process, slice_observation
from agent_actions.workflow.runner_file_processing import (
    process_directory_files,
    process_from_storage_backend,
    process_merged_files,
)

ACTION = "flatten"


class _Backend:
    """Enough storage backend for the walk; a real class so the observation
    registry can hold it weakly and so no attribute answers truthy by accident."""

    def __init__(self, by_action, *, list_errors=(), read_errors=()):
        self._by_action = by_action
        self._list_errors = set(list_errors)
        self._read_errors = set(read_errors)

    def list_target_files(self, action_name):
        if action_name in self._list_errors:
            raise OSError("database is locked")
        return list(self._by_action.get(action_name, {}))

    def read_target(self, action_name, relative_path):
        if (action_name, relative_path) in self._read_errors:
            raise json.JSONDecodeError("bad blob", "", 0)
        return self._by_action[action_name][relative_path]

    def load_metadata(self, _key):
        return None

    def get_disposition(self, *_args, **_kwargs):
        return []


def _records(count: int) -> list[dict[str, str]]:
    return [{"source_guid": f"g{i}"} for i in range(count)]


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)


def _params(tmp_path, upstream_dirs=None):
    params = MagicMock()
    params.action_config = {}
    params.action_name = ACTION
    params.strategy = MagicMock()
    params.idx = 0
    params.file_type_filter = None
    params.output_directory = str(tmp_path / "output")
    params.upstream_data_dirs = upstream_dirs or []
    return params


def _slices(backend, count=4):
    """A per-file callback that slices normally, as a healthy file would."""

    def _run(_file_params):
        record_indices_to_process(_records(count), {}, ACTION, storage_backend=backend)

    return _run


class TestTheStagingWalk:
    """process_directory_files — the filesystem fallback."""

    def _walk(self, tmp_path, backend, per_file):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        for name in ("a.json", "b.json"):
            (input_dir / name).write_text(json.dumps([{"id": name}]))
        output = tmp_path / "output"
        output.mkdir()

        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = per_file

        return process_directory_files(
            runner, input_dir, output, str(input_dir), _params(tmp_path), set()
        )

    def test_a_file_that_fails_leaves_the_action_count_unknown(self, tmp_path):
        backend = _Backend({})
        calls = {"n": 0}

        def per_file(params):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("unreadable input")
            _slices(backend)(params)

        _found, processed, _errors = self._walk(tmp_path, backend, per_file)

        assert processed == 1, "the walk tolerates the failure and completes"
        assert slice_observation(backend, ACTION) is None

    def test_a_file_that_fails_after_the_others_still_poisons(self, tmp_path):
        """Order must not matter: the records are missing either way."""
        backend = _Backend({})
        calls = {"n": 0}

        def per_file(params):
            calls["n"] += 1
            if calls["n"] == 2:
                raise ValueError("unreadable input")
            _slices(backend)(params)

        self._walk(tmp_path, backend, per_file)

        assert slice_observation(backend, ACTION) is None

    def test_a_clean_walk_keeps_its_count(self, tmp_path):
        """The guard must not cost a run that lost nothing its precision."""
        backend = _Backend({})

        self._walk(tmp_path, backend, _slices(backend, 3))

        assert slice_observation(backend, ACTION) == (6, False)


class TestTheMergedWalk:
    """process_merged_files — the fan-in path."""

    def _walk(self, tmp_path, backend, per_file):
        upstream = tmp_path / "upstream"
        upstream.mkdir()
        output = tmp_path / "output"
        output.mkdir()
        for i in range(2):
            (upstream / f"file_{i}.json").write_text(json.dumps([{"id": i}]))

        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._collect_files_from_upstream.return_value = {
            Path(f"file_{i}.json"): [upstream / f"file_{i}.json"] for i in range(2)
        }
        runner._process_single_file.side_effect = per_file

        params = _params(tmp_path, [str(upstream)])
        return process_merged_files(runner, params)

    def test_a_merged_file_that_fails_leaves_the_action_count_unknown(self, tmp_path):
        backend = _Backend({})
        calls = {"n": 0}

        def per_file(params):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("unreadable merge input")
            _slices(backend)(params)

        self._walk(tmp_path, backend, per_file)

        assert slice_observation(backend, ACTION) is None

    def test_a_clean_merged_walk_keeps_its_count(self, tmp_path):
        backend = _Backend({})

        self._walk(tmp_path, backend, _slices(backend, 3))

        assert slice_observation(backend, ACTION) == (6, False)


class TestTheStorageBackendWalk:
    """process_from_storage_backend — the default path for a dependent action
    in a project with a store, and the one the reported failure came from."""

    def _walk(self, tmp_path, backend, per_file, upstreams=("extract",)):
        output = tmp_path / "output"
        output.mkdir()
        dirs = []
        for name in upstreams:
            upstream = tmp_path / "agent_io" / "target" / name
            upstream.mkdir(parents=True)
            dirs.append(str(upstream))

        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = per_file

        return process_from_storage_backend(runner, _params(tmp_path, dirs))

    def test_an_entry_that_fails_to_process_leaves_the_count_unknown(self, tmp_path):
        backend = _Backend({"extract": {"a.json": _records(4), "b.json": _records(4)}})
        calls = {"n": 0}

        def per_file(params):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("processing blew up")
            _slices(backend)(params)

        self._walk(tmp_path, backend, per_file)

        assert slice_observation(backend, ACTION) is None

    def test_an_entry_that_fails_to_read_leaves_the_count_unknown(self, tmp_path):
        """A stored blob that will not parse is the reported failure verbatim.
        It never reaches the per-entry handler — the entry is dropped before the
        processing loop, so it is not even counted in files_found, and the
        sibling entry that did read goes on to slice a short count."""
        backend = _Backend(
            {"extract": {"a.json": _records(4), "b.json": _records(9)}},
            read_errors={("extract", "b.json")},
        )

        _found, processed, _errors = self._walk(tmp_path, backend, _slices(backend))

        assert processed == 1, "the run completes on the entries it could read"
        assert slice_observation(backend, ACTION) is None

    def test_an_upstream_whose_listing_fails_leaves_the_count_unknown(self, tmp_path):
        """A locked or unreadable store loses every file of that upstream at
        once — exactly the failure the next run would have recovered from. The
        second upstream still slices, so without the guard the action would
        carry a count covering only half its inputs."""
        backend = _Backend(
            {"extract": {"a.json": _records(9)}, "enrich": {"b.json": _records(4)}},
            list_errors={"extract"},
        )

        self._walk(tmp_path, backend, _slices(backend), upstreams=("extract", "enrich"))

        assert slice_observation(backend, ACTION) is None

    def test_a_clean_backend_walk_keeps_its_count(self, tmp_path):
        backend = _Backend({"extract": {"a.json": _records(4), "b.json": _records(4)}})

        self._walk(tmp_path, backend, _slices(backend, 3))

        assert slice_observation(backend, ACTION) == (6, False)
