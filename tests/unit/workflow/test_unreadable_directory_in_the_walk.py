"""A staging directory the walk cannot open must not lose its files in silence (1096).

``Path.rglob`` swallows the ``OSError`` ``scandir`` raises for such a directory:
the entry itself comes back, so the per-entry regular-file check answers "not a
file" correctly and the loss path never fires, while every file beneath it is
dropped with no exception, no log line and no error row. Since 610/625 that
under-count reads as "a smaller record limit could not have bitten", so the
action is skipped next run and its short output vouched for. Permission is
normally set on a directory rather than on each file, so this is the common
shape of the loss.
"""

import json
import os
from unittest.mock import MagicMock

import pytest

from agent_actions.utils.limits import record_indices_to_process, slice_observation
from agent_actions.workflow.runner_file_processing import (
    collect_files_from_upstream,
    process_directory_files,
    process_files,
    process_merged_files,
)

ACTION = "flatten"

pytestmark = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root reads a mode-000 directory, so the loss cannot be staged",
)


class _Backend:
    """Enough storage backend for the walk; a real class so the observation
    registry can hold it weakly and so no attribute answers truthy by accident."""

    def load_metadata(self, _key):
        return None

    def get_disposition(self, *_args, **_kwargs):
        return []


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)


@pytest.fixture
def locked_dirs():
    """chmod 000 for the body of a test, restored so tmp_path teardown can run."""
    made: list = []

    def _lock(path):
        path.chmod(0o000)
        made.append(path)
        return path

    yield _lock
    for path in made:
        path.chmod(0o755)


def _staging(tmp_path, locked_dirs, *, readable=("a.json", "b.json"), hidden=("hidden.json",)):
    """An input directory holding *readable* files plus a subtree nothing can open."""
    root = tmp_path / "staging"
    root.mkdir()
    for name in readable:
        (root / name).write_text(json.dumps([{"id": name}]))
    locked = root / "locked"
    locked.mkdir()
    for name in hidden:
        (locked / name).write_text(json.dumps([{"id": name}]))
    locked_dirs(locked)
    return root


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


def _records(count: int) -> list[dict[str, str]]:
    return [{"source_guid": f"g{i}"} for i in range(count)]


def _slices(backend, count=4):
    """A per-file callback that slices normally, as a healthy file would."""

    def _run(_file_params):
        record_indices_to_process(_records(count), {}, ACTION, storage_backend=backend)

    return _run


def _runner(backend, per_file):
    runner = MagicMock()
    runner.retried_records = frozenset()
    runner.storage_backend = backend
    runner._process_single_file.side_effect = per_file
    return runner


def _seen_names(runner):
    """The files the walk actually handed to the per-file callback."""
    return sorted(
        call.args[0].locations.item.name for call in runner._process_single_file.mock_calls
    )


class TestTheStagingWalk:
    """process_directory_files — the filesystem walk over one upstream."""

    def _walk(self, tmp_path, locked_dirs, backend, per_file, **kwargs):
        root = _staging(tmp_path, locked_dirs, **kwargs)
        output = tmp_path / "output"
        output.mkdir()
        runner = _runner(backend, per_file)
        found, processed, errors = process_directory_files(
            runner, root, output, str(root), _params(tmp_path), set()
        )
        return runner, found, processed, errors

    def test_the_hidden_file_really_is_lost(self, tmp_path, locked_dirs):
        """The premise. If a future Python raised instead of dropping the subtree,
        every other test here would pass while proving nothing."""
        backend = _Backend()

        runner, _found, _processed, _errors = self._walk(
            tmp_path, locked_dirs, backend, _slices(backend)
        )

        assert _seen_names(runner) == ["a.json", "b.json"]

    def test_the_directory_it_could_not_open_is_reported(self, tmp_path, locked_dirs):
        backend = _Backend()

        _runner_, _found, _processed, errors = self._walk(
            tmp_path, locked_dirs, backend, _slices(backend)
        )

        assert any("locked" in message for message in errors.messages), errors.messages

    def test_it_is_counted_among_the_files_found(self, tmp_path, locked_dirs):
        """Counted as found and never as processed: that gap is what makes an
        action whose whole input was unreadable fail instead of complete empty."""
        backend = _Backend()

        _runner_, found, processed, _errors = self._walk(
            tmp_path, locked_dirs, backend, _slices(backend)
        )

        assert (found, processed) == (3, 2)

    def test_the_action_record_count_goes_unknown(self, tmp_path, locked_dirs):
        """The damage the loss does: the two readable files slice and stamp a
        count that silently omits whatever was under `locked`."""
        backend = _Backend()

        self._walk(tmp_path, locked_dirs, backend, _slices(backend))

        assert slice_observation(backend, ACTION) is None

    def test_a_batch_directory_it_cannot_open_is_not_a_loss(self, tmp_path, locked_dirs):
        """`batch` is skipped whether or not it opens, so reporting it would fail
        an action that lost nothing — the one direction this fix must not add."""
        backend = _Backend()
        root = tmp_path / "staging"
        root.mkdir()
        (root / "a.json").write_text(json.dumps([{"id": "a"}]))
        batch = root / "batch"
        batch.mkdir()
        (batch / "queued.json").write_text(json.dumps([{"id": "queued"}]))
        locked_dirs(batch)
        (tmp_path / "output").mkdir()

        found, processed, errors = process_directory_files(
            _runner(backend, _slices(backend, 3)),
            root,
            tmp_path / "output",
            str(root),
            _params(tmp_path),
            set(),
        )

        assert (found, processed, errors.messages) == (1, 1, [])
        assert slice_observation(backend, ACTION) == (3, False)

    def test_a_readable_tree_keeps_its_count(self, tmp_path, locked_dirs):
        """The guard: a walk that lost nothing must not pay for this."""
        backend = _Backend()
        root = tmp_path / "staging"
        root.mkdir()
        for name in ("a.json", "b.json"):
            (root / name).write_text(json.dumps([{"id": name}]))
        (tmp_path / "output").mkdir()

        found, processed, errors = process_directory_files(
            _runner(backend, _slices(backend, 3)),
            root,
            tmp_path / "output",
            str(root),
            _params(tmp_path),
            set(),
        )

        assert (found, processed, errors.messages) == (2, 2, [])
        assert slice_observation(backend, ACTION) == (6, False)


class TestAnInputNothingCanRead:
    """The whole-input case, through the orchestrator that decides the outcome."""

    def _run(self, tmp_path, locked_dirs, backend):
        root = tmp_path / "staging"
        root.mkdir()
        (root / "a.json").write_text(json.dumps([{"id": "a"}]))
        (tmp_path / "output").mkdir()
        locked_dirs(root)
        params = _params(tmp_path, [str(root)])
        process_files(_runner(backend, _slices(backend)), params)

    def test_the_action_fails_rather_than_completing_empty(self, tmp_path, locked_dirs):
        """Today the walk returns nothing found, `warn_no_files_found` logs at
        debug, and the action completes as though its input were empty."""
        from agent_actions.errors import DependencyError

        with pytest.raises(DependencyError) as raised:
            self._run(tmp_path, locked_dirs, _Backend())

        assert "staging" in str(raised.value)


class TestTheMergedWalk:
    """process_merged_files — the fan-in path, whose collector walks each upstream."""

    def _walk(self, tmp_path, locked_dirs, backend, per_file):
        dirs = []
        for up_name in ("up_a", "up_b"):
            upstream = tmp_path / up_name
            upstream.mkdir()
            (upstream / "f.json").write_text(json.dumps([{"id": up_name}]))
            dirs.append(str(upstream))
        locked = tmp_path / "up_b" / "locked"
        locked.mkdir()
        (locked / "g.json").write_text(json.dumps([{"id": "hidden"}]))
        locked_dirs(locked)
        (tmp_path / "output").mkdir()

        return process_merged_files(_runner(backend, per_file), _params(tmp_path, dirs))

    def test_the_directory_it_could_not_open_is_reported(self, tmp_path, locked_dirs):
        backend = _Backend()

        _found, _processed, errors = self._walk(tmp_path, locked_dirs, backend, _slices(backend))

        assert any("locked" in message for message in errors.messages), errors.messages

    def test_it_is_counted_among_the_files_found(self, tmp_path, locked_dirs):
        """One merged group from the two `f.json` files, plus the directory."""
        backend = _Backend()

        found, processed, _errors = self._walk(tmp_path, locked_dirs, backend, _slices(backend))

        assert (found, processed) == (2, 1)

    def test_the_action_record_count_goes_unknown(self, tmp_path, locked_dirs):
        backend = _Backend()

        self._walk(tmp_path, locked_dirs, backend, _slices(backend))

        assert slice_observation(backend, ACTION) is None

    def test_a_readable_pair_of_upstreams_keeps_its_count(self, tmp_path, locked_dirs):
        backend = _Backend()
        dirs = []
        for up_name in ("up_a", "up_b"):
            upstream = tmp_path / up_name
            upstream.mkdir()
            (upstream / "f.json").write_text(json.dumps([{"id": up_name}]))
            dirs.append(str(upstream))
        (tmp_path / "output").mkdir()

        found, processed, errors = process_merged_files(
            _runner(backend, _slices(backend, 3)), _params(tmp_path, dirs)
        )

        assert (found, processed, errors.messages) == (1, 1, [])
        assert slice_observation(backend, ACTION) == (3, False)


class TestTheCollector:
    """collect_files_from_upstream — reached by the merged walk, and the second
    of the two enumerations the report has to come out of."""

    def test_it_reports_the_directory_it_could_not_open(self, tmp_path, locked_dirs):
        root = _staging(tmp_path, locked_dirs)
        unreadable: list = []

        collect_files_from_upstream([str(root)], unreadable)

        assert [str(where) for where, _exc in unreadable] == ["locked"]

    def test_it_still_returns_the_files_it_could_read(self, tmp_path, locked_dirs):
        root = _staging(tmp_path, locked_dirs)
        unreadable: list = []

        collected = collect_files_from_upstream([str(root)], unreadable)

        assert sorted(str(path) for path in collected) == ["a.json", "b.json"]

    def test_a_readable_tree_reports_nothing(self, tmp_path):
        root = tmp_path / "staging"
        root.mkdir()
        (root / "a.json").write_text("[]")
        unreadable: list = []

        collected = collect_files_from_upstream([str(root)], unreadable)

        assert (sorted(str(path) for path in collected), unreadable) == (["a.json"], [])
