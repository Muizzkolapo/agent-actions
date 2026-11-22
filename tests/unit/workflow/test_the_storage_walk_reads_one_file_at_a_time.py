"""The storage walk reads each stored file as it processes it, and lets it go before the next.

It read every file of every upstream before processing the first, and held them all
until the walk ended, so an action's memory grew with its whole input rather than with
its largest file (#1865).
"""

import gc
import weakref
from typing import Any
from unittest.mock import MagicMock

from agent_actions.workflow.runner_file_processing import process_from_storage_backend

ACTION = "summarise"


class _Rows(list):
    """A stored file's rows; a list subclass so the test can hold it weakly."""


class _Backend:
    def __init__(self, files: dict[str, dict[str, list[dict[str, Any]]]], events: list):
        self._files = files
        self._events = events
        self.read: dict[str, weakref.ref] = {}

    def list_target_files(self, action_name):
        return list(self._files.get(action_name, {}))

    def read_target(self, action_name, relative_path):
        self._events.append(("read", action_name, relative_path))
        rows = _Rows(dict(row) for row in self._files[action_name][relative_path])
        self.read[f"{action_name}/{relative_path}"] = weakref.ref(rows)
        return rows

    def load_metadata(self, _key):
        return None

    def get_disposition(self, *_args, **_kwargs):
        return []


def _walk(tmp_path, backend: _Backend, upstreams: tuple[str, ...], per_file):
    dirs = []
    for name in upstreams:
        upstream = tmp_path / "agent_io" / "target" / name
        upstream.mkdir(parents=True, exist_ok=True)
        dirs.append(str(upstream))
    params = MagicMock()
    params.action_config = {}
    params.action_name = ACTION
    params.output_directory = str(tmp_path / "output")
    params.upstream_data_dirs = dirs
    params.correlated_input = None
    runner = MagicMock()
    runner.retried_records = frozenset()
    runner.storage_backend = backend
    runner._process_single_file = per_file
    return process_from_storage_backend(runner, params)


def test_each_file_is_read_as_it_is_processed(tmp_path):
    events: list = []
    backend = _Backend(
        {"extract": {"b.json": [{"source_guid": "b1"}], "a.json": [{"source_guid": "a1"}]}},
        events,
    )

    def per_file(file_params):
        events.append(("process", file_params.data[0]["source_guid"]))

    found, processed, _errors = _walk(tmp_path, backend, ("extract",), per_file)

    assert events == [
        ("read", "extract", "a.json"),
        ("process", "a1"),
        ("read", "extract", "b.json"),
        ("process", "b1"),
    ]
    assert (found, processed) == (2, 2)


def test_a_processed_file_is_let_go_before_the_next_is_read(tmp_path):
    events: list = []
    backend = _Backend(
        {"extract": {"a.json": [{"source_guid": "a1"}], "b.json": [{"source_guid": "b1"}]}},
        events,
    )
    still_held: list[bool] = []

    def per_file(file_params):
        if "extract/a.json" in backend.read and file_params.data[0]["source_guid"] == "b1":
            gc.collect()
            still_held.append(backend.read["extract/a.json"]() is not None)

    _walk(tmp_path, backend, ("extract",), per_file)

    assert still_held == [False]


def test_a_fan_in_reads_each_branch_of_one_file_before_the_next_file(tmp_path):
    events: list = []
    backend = _Backend(
        {
            "left": {"a.json": [{"source_guid": "a1"}], "b.json": [{"source_guid": "b1"}]},
            "right": {"a.json": [{"source_guid": "a1"}], "b.json": [{"source_guid": "b1"}]},
        },
        events,
    )

    def per_file(file_params):
        events.append(("process", file_params.data[0]["source_guid"]))

    found, processed, _errors = _walk(tmp_path, backend, ("left", "right"), per_file)

    assert events == [
        ("read", "left", "a.json"),
        ("read", "right", "a.json"),
        ("process", "a1"),
        ("read", "left", "b.json"),
        ("read", "right", "b.json"),
        ("process", "b1"),
    ]
    assert (found, processed) == (2, 2)
