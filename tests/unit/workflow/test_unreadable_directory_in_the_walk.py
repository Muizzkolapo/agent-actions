"""A staging directory the walk cannot open must not lose its files in silence (1096).

``Path.rglob`` swallows the ``OSError`` ``scandir`` raises for such a directory:
the entry comes back, so the regular-file check answers "not a file" correctly
and the loss path never fires, while every file beneath it is dropped with no
exception, no log line and no error row. Since 610/625 that under-count reads
as "a smaller record limit could not have bitten", so the action is skipped
next run and its short output vouched for — and permission is normally set on
a directory, not on each file, so this is the common shape of the loss.
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

        assert [message.split(":")[0] for message in errors.messages] == ["locked"]

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

    def test_several_are_reported_in_a_stable_order(self, tmp_path, locked_dirs):
        """`errors` keeps only the first _MAX_TRACKED_ERRORS, so without a sort it
        is filesystem order that decides which losses get named at all."""
        backend = _Backend()
        root = tmp_path / "staging"
        root.mkdir()
        (root / "a.json").write_text(json.dumps([{"id": "a"}]))
        for name in ("m_two", "z_three", "b_one"):
            directory = root / name
            directory.mkdir()
            locked_dirs(directory)
        (tmp_path / "output").mkdir()

        _found, _processed, errors = process_directory_files(
            _runner(backend, _slices(backend)),
            root,
            tmp_path / "output",
            str(root),
            _params(tmp_path),
            set(),
        )

        assert [m.split(":")[0] for m in errors.messages] == ["b_one", "m_two", "z_three"]

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

        assert str(raised.value).startswith("Action 'flatten': staging: [Errno 13]")


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

        assert [message.split(":")[0] for message in errors.messages] == ["locked"]

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


class TestAnUnreadableUpstreamRoot:
    """A fan-in whose whole upstream will not open. The label has to name that
    upstream: the DependencyError's text is the only place its identity appears,
    since `upstream_dirs` goes to the error's context rather than its message."""

    def _dirs(self, tmp_path, locked_dirs, lock=("up_b",)):
        dirs = []
        for name in ("up_a", "up_b"):
            upstream = tmp_path / name
            upstream.mkdir()
            (upstream / "f.json").write_text(json.dumps([{"id": name}]))
            dirs.append(str(upstream))
        for name in lock:
            locked_dirs(tmp_path / name)
        (tmp_path / "output").mkdir()
        return dirs

    def test_the_error_names_the_upstream_rather_than_a_bare_dot(self, tmp_path, locked_dirs):
        backend = _Backend()
        dirs = self._dirs(tmp_path, locked_dirs)

        _found, _processed, errors = process_merged_files(
            _runner(backend, _slices(backend)), _params(tmp_path, dirs)
        )

        assert [message.split(":")[0] for message in errors.messages] == ["up_b"]

    def test_the_readable_upstream_still_merges(self, tmp_path, locked_dirs):
        backend = _Backend()
        dirs = self._dirs(tmp_path, locked_dirs)

        found, processed, _errors = process_merged_files(
            _runner(backend, _slices(backend)), _params(tmp_path, dirs)
        )

        assert (found, processed) == (2, 1)

    def test_losing_every_upstream_fails_the_action(self, tmp_path, locked_dirs):
        from agent_actions.errors import DependencyError

        backend = _Backend()
        dirs = self._dirs(tmp_path, locked_dirs, lock=("up_a", "up_b"))

        with pytest.raises(DependencyError) as raised:
            process_files(_runner(backend, _slices(backend)), _params(tmp_path, dirs))

        assert "up_a" in str(raised.value) and "up_b" in str(raised.value)


class _RepairBackend(_Backend):
    """Enough backend for the repair narrowing: which files hold the named records."""

    def __init__(self, wanted, shares_chain=False):
        self._wanted = wanted
        self._shares_chain = shares_chain

    def records_share_a_repeat_chain(self, _retried):
        return self._shares_chain

    def source_files_for_records(self, _retried):
        return self._wanted


class TestARepairIsReportedLikeAnyOtherWalk:
    """A repair is not exempt from the report, though its walk is narrowed.

    The store resolves ids to staging paths with a set union, so an id resolving to
    nothing leaves no trace: "unrelated to what the store named" is not "unrelated
    to what the repair needs", and the file behind the lock may be the one being
    repaired. Reporting is not free — the loss counts toward `files_found`, so a
    repair whose other files are all skipped raises rather than completing. That
    trade is deliberate: a named permission fault over a silent no-op repair.
    """

    def _walk(self, tmp_path, backend, *, readable=("a.json",)):
        root = _staging(tmp_path, self._lock, readable=readable, hidden=("x.json",))
        (tmp_path / "output").mkdir()
        runner = _runner(backend, lambda _p: None)
        runner.retried_records = frozenset({"rec1"})
        return process_directory_files(
            runner, root, tmp_path / "output", str(root), _params(tmp_path), set()
        )

    @pytest.fixture(autouse=True)
    def _lock_fixture(self, locked_dirs):
        self._lock = locked_dirs

    def test_a_narrowed_repair_still_reports_the_directory(self, tmp_path):
        found, processed, errors = self._walk(tmp_path, _RepairBackend({"a"}))

        assert (found, processed) == (2, 1)
        assert [message.split(":")[0] for message in errors.messages] == ["locked"]

    def test_a_named_file_the_walk_never_saw_is_reported(self, tmp_path):
        """It may be sitting inside the directory that would not open."""
        found, processed, errors = self._walk(tmp_path, _RepairBackend({"nowhere"}))

        assert (found, processed) == (1, 0)
        assert [message.split(":")[0] for message in errors.messages] == ["locked"]

    def test_a_record_the_store_cannot_place_does_not_silence_the_report(self, tmp_path):
        """The shape an exemption keyed on the store would miss: `source_files_for_records`
        is a set union, so a retried id with no source row simply contributes nothing
        to the wanted set — and its staging file may be the one behind the lock."""
        found, processed, errors = self._walk(tmp_path, _RepairBackend({"a"}))

        assert [message.split(":")[0] for message in errors.messages] == ["locked"]

    def test_a_repair_that_fell_back_to_walking_everything_still_reports(self, tmp_path):
        found, processed, errors = self._walk(tmp_path, _RepairBackend({"a"}, shares_chain=True))

        assert (found, processed) == (2, 1)
        assert [message.split(":")[0] for message in errors.messages] == ["locked"]


class TestAPartialLossThroughTheOrchestrator:
    """The walk functions are tested directly elsewhere; this drives `process_files`,
    which is what decides the action's fate. A directory loss must NOT be action-fatal:
    an implementation that tagged the OSError with `_ACTION_FATAL_KEY` would satisfy
    every other test here while hard-failing any action that has one unreadable
    subdirectory among readable files."""

    def test_the_readable_files_still_process_and_the_action_survives(self, tmp_path, locked_dirs):
        backend = _Backend()
        root = _staging(tmp_path, locked_dirs)
        (tmp_path / "output").mkdir()
        runner = _runner(backend, _slices(backend))

        process_files(runner, _params(tmp_path, [str(root)]))

        assert _seen_names(runner) == ["a.json", "b.json"]
        assert slice_observation(backend, ACTION) is None


class TestTheCollector:
    """collect_files_from_upstream — reached by the merged walk, and the second
    of the two enumerations the report has to come out of. Its losses ride in
    the same list a file the walk cannot stat uses, so the caller drains one."""

    def test_it_reports_the_directory_it_could_not_open(self, tmp_path, locked_dirs):
        root = _staging(tmp_path, locked_dirs)

        _collected, lost = collect_files_from_upstream([str(root)])

        assert [path.name for path, _exc in lost] == ["locked"]

    def test_it_still_returns_the_files_it_could_read(self, tmp_path, locked_dirs):
        root = _staging(tmp_path, locked_dirs)

        collected, _lost = collect_files_from_upstream([str(root)])

        assert sorted(str(path) for path in collected) == ["a.json", "b.json"]

    def test_a_readable_tree_reports_nothing(self, tmp_path):
        root = tmp_path / "staging"
        root.mkdir()
        (root / "a.json").write_text("[]")

        collected, lost = collect_files_from_upstream([str(root)])

        assert (sorted(str(path) for path in collected), lost) == (["a.json"], [])
