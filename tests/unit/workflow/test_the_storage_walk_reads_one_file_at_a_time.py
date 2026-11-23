"""The storage walk holds one stored file at a time, and still refuses a bad store up front.

It read every file of every upstream before processing the first, and held them all
until the walk ended, so an action's memory grew with its whole input rather than with
its largest file (#1865). Each file is now read once to check it and let go, then read
again when its turn comes and let go before the next. The store keeps every file it
reconstructs until something is written, and a batch action writes nothing while it
prepares, so the walk drops each file from that cache too.
"""

import gc
import weakref
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.runner_file_processing import process_from_storage_backend

ACTION = "summarise"
UPSTREAM = "extract"


def _params(tmp_path: Path, upstreams: tuple[str, ...]) -> MagicMock:
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
    return params


def _runner(backend: Any, per_file) -> MagicMock:
    runner = MagicMock()
    runner.retried_records = frozenset()
    runner.storage_backend = backend
    runner.action_configs = {}
    runner._process_single_file = per_file
    return runner


def _stored(guid: str, **fields: Any) -> dict[str, Any]:
    return {"source_guid": guid, "content": {UPSTREAM: {"text": guid}}, **fields}


@pytest.fixture
def backend(tmp_path: Path):
    store = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="wf")
    store.initialize()
    yield store
    store.close()


def _store(backend: SQLiteBackend, files: dict[str, list[dict[str, Any]]]) -> None:
    for name, rows in files.items():
        backend._write_target_raw(UPSTREAM, name, [{**row, "_delta_mode": "full"} for row in rows])
    backend._reconstruction_cache.clear()


def test_the_store_holds_at_most_one_walked_file_while_a_batch_action_prepares(tmp_path, backend):
    names = [f"f{i:02d}.json" for i in range(6)]
    _store(backend, {name: [_stored(name, _state="processed")] for name in names})
    cached_while_processing: list[int] = []

    def prepares_without_writing(file_params):
        cached_while_processing.append(len(backend._reconstruction_cache))

    found, processed, errors = process_from_storage_backend(
        _runner(backend, prepares_without_writing), _params(tmp_path, (UPSTREAM,))
    )

    assert (found, processed, errors.messages) == (6, 6, [])
    assert cached_while_processing == [1] * 6
    assert backend._reconstruction_cache == {}


def test_a_fan_in_holds_only_the_branches_of_the_entry_it_processes(tmp_path, backend):
    names = ["a.json", "b.json", "c.json"]
    for upstream in ("left", "right"):
        for name in names:
            backend._write_target_raw(
                upstream,
                name,
                [
                    {
                        "source_guid": name,
                        "content": {upstream: {"text": name}},
                        "_state": "processed",
                        "_delta_mode": "full",
                    }
                ],
            )
    backend._reconstruction_cache.clear()
    cached_while_processing: list[set[tuple[str, str]]] = []

    def prepares_without_writing(file_params):
        cached_while_processing.append(set(backend._reconstruction_cache))

    found, processed, errors = process_from_storage_backend(
        _runner(backend, prepares_without_writing), _params(tmp_path, ("left", "right"))
    )

    assert (found, processed, errors.messages) == (3, 3, [])
    assert cached_while_processing == [{("left", name), ("right", name)} for name in names]
    assert backend._reconstruction_cache == {}


def test_a_record_in_no_lifecycle_state_stops_the_action_before_any_file_is_processed(
    tmp_path, backend
):
    _store(
        backend,
        {"a.json": [_stored("a1", _state="processed")], "b.json": [_stored("b1")]},
    )
    processed: list[Any] = []

    with pytest.raises(ConfigurationError):
        process_from_storage_backend(
            _runner(backend, processed.append), _params(tmp_path, (UPSTREAM,))
        )

    assert processed == []


class _Rows(list):
    """A stored file's rows; a list subclass so the test can hold it weakly."""


class _Backend:
    def __init__(
        self,
        files: dict[str, dict[str, list[dict[str, Any]]]],
        events: list,
        *,
        unreadable: frozenset[tuple[str, str]] = frozenset(),
        on_read=None,
    ):
        self._files = files
        self._events = events
        self._unreadable = unreadable
        self._on_read = on_read
        self.read: dict[str, weakref.ref] = {}

    def list_target_files(self, action_name):
        return list(self._files.get(action_name, {}))

    def read_target(self, action_name, relative_path):
        self._events.append(("read", action_name, relative_path))
        if self._on_read is not None:
            self._on_read(action_name, relative_path)
        if (action_name, relative_path) in self._unreadable:
            raise OSError(f"{relative_path} is gone")
        rows = _Rows(dict(row) for row in self._files[action_name][relative_path])
        self.read[f"{action_name}/{relative_path}"] = weakref.ref(rows)
        return rows

    def forget_reconstructed(self, action_name, relative_path):
        self._events.append(("forget", action_name, relative_path))

    def load_metadata(self, _key):
        return None

    def get_disposition(self, *_args, **_kwargs):
        return []


def test_each_file_is_checked_up_front_then_read_as_it_is_processed(tmp_path):
    events: list = []
    backend = _Backend(
        {"extract": {"b.json": [{"source_guid": "b1"}], "a.json": [{"source_guid": "a1"}]}},
        events,
    )

    def per_file(file_params):
        events.append(("process", file_params.data[0]["source_guid"]))

    found, processed, _errors = process_from_storage_backend(
        _runner(backend, per_file), _params(tmp_path, ("extract",))
    )

    assert events == [
        ("read", "extract", "b.json"),
        ("forget", "extract", "b.json"),
        ("read", "extract", "a.json"),
        ("forget", "extract", "a.json"),
        ("read", "extract", "a.json"),
        ("process", "a1"),
        ("forget", "extract", "a.json"),
        ("read", "extract", "b.json"),
        ("process", "b1"),
        ("forget", "extract", "b.json"),
    ]
    assert (found, processed) == (2, 2)


def test_a_processed_file_is_let_go_before_the_next_is_read(tmp_path):
    events: list = []
    held_while_reading_the_next: list[bool] = []

    def on_read(action_name, relative_path):
        # The read that processes b.json comes after a.json was processed.
        if relative_path == "b.json" and ("process", "a1") in events:
            gc.collect()
            held_while_reading_the_next.append(backend.read["extract/a.json"]() is not None)

    backend = _Backend(
        {"extract": {"a.json": [{"source_guid": "a1"}], "b.json": [{"source_guid": "b1"}]}},
        events,
        on_read=on_read,
    )

    def per_file(file_params):
        events.append(("process", file_params.data[0]["source_guid"]))

    process_from_storage_backend(_runner(backend, per_file), _params(tmp_path, ("extract",)))

    assert held_while_reading_the_next == [False]


@pytest.mark.parametrize(
    ("files", "lost", "found"),
    [
        pytest.param(("a.json", "b.json"), "b.json", 2, id="the_lost_file_after_the_limit"),
        pytest.param(("a.json", "b.json", "c.json"), "c.json", 3, id="past_the_limit_of_three"),
        pytest.param(("a.json", "b.json", "c.json"), "a.json", 3, id="the_lost_file_first"),
    ],
)
def test_a_file_limit_counts_a_lost_file_once(tmp_path, monkeypatch, files, lost, found):
    monkeypatch.delenv("AGAC_FILE_LIMIT", raising=False)
    events: list = []
    backend = _Backend(
        {"extract": {name: [{"source_guid": name}] for name in files}},
        events,
        unreadable=frozenset({("extract", lost)}),
    )
    params = _params(tmp_path, ("extract",))
    params.action_config = {"file_limit": 1}

    counted, processed, errors = process_from_storage_backend(
        _runner(backend, lambda file_params: None), params
    )

    # Every file found once, the lost one as lost, as when every file was held.
    assert (counted, processed) == (found, 1)
    assert len(errors.messages) == 1 and lost in errors.messages[0]


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

    found, processed, _errors = process_from_storage_backend(
        _runner(backend, per_file), _params(tmp_path, ("left", "right"))
    )

    processing = [event for event in events if event[0] != "forget"][4:]
    assert processing == [
        ("read", "left", "a.json"),
        ("read", "right", "a.json"),
        ("process", "a1"),
        ("read", "left", "b.json"),
        ("read", "right", "b.json"),
        ("process", "b1"),
    ]
    assert (found, processed) == (2, 2)
