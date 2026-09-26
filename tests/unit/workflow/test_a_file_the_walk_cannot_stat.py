"""A staged file the filesystem will not describe is a loss, not a skip (1026).

``Path.is_file()`` answers a question it cannot always answer: it catches the
``OSError`` from the underlying ``stat()`` and returns ``False``. So a
permission-denied file, a dangling symlink and a transient I/O error are
indistinguishable from "this is a directory", and the walk drops them with no
exception, no error record and no log line.

Every other skip in the walk is deliberate — a batch directory, a dotfile, an
already-processed path, a filtered suffix. This one is not, and #1027 gave the
walk the mechanism it needs: a per-file failure calls ``_lose_file`` and takes
the action's record count out of service, because an under-count is the one
error that reads as "a smaller limit could not have bitten".

Two walkers decide "not a file" that way, so both are covered: the staging walk
through ``should_skip_item``, and ``collect_files_from_upstream``, which inlines
the same three checks for the merge walk.
"""

import json
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.utils.limits import record_indices_to_process, slice_observation
from agent_actions.workflow.runner_file_processing import (
    collect_files_from_upstream,
    process_directory_files,
    process_merged_files,
    should_skip_item,
)

ACTION = "flatten"


class _Backend:
    """Enough backend for the slice registry, which holds it weakly."""

    def __init__(self):
        self.written: list[str] = []

    def write_target(self, action_name, relative_path, data):
        self.written.append(relative_path)

    def list_target_files(self, action_name):
        return []

    def load_metadata(self, _key):
        return None

    def get_disposition(self, *_args, **_kwargs):
        return []


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv("AGAC_MAX_RECORDS", raising=False)


def _params(tmp_path, upstream_dirs=None, action_config=None):
    params = MagicMock()
    params.action_config = action_config if action_config is not None else {}
    params.action_name = ACTION
    params.strategy = MagicMock()
    params.idx = 0
    params.file_type_filter = None
    params.output_directory = str(tmp_path / "output")
    params.upstream_data_dirs = upstream_dirs or []
    return params


def _slices(backend, count=4):
    def _run(_file_params):
        records = [{"source_guid": f"g{i}"} for i in range(count)]
        record_indices_to_process(records, {}, ACTION, storage_backend=backend)

    return _run


def _staging(tmp_path, *, names=("a.json",), dangling=()):
    """A staging directory holding real files and symlinks pointing nowhere.

    A dangling symlink is the portable way to make ``stat()`` fail: it needs no
    permission games, raises ``ENOENT`` on every platform the suite runs on, and
    is one of the cases the reported bug names.
    """
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (input_dir / name).write_text(json.dumps([{"id": name}]))
    for name in dangling:
        (input_dir / name).symlink_to(input_dir / "does-not-exist.json")
    (tmp_path / "output").mkdir(exist_ok=True)
    return input_dir


class TestTheHelperSeparatesNotAFileFromCannotTell:
    """``should_skip_item`` is the staging walk's only skip decision."""

    def test_a_file_that_cannot_be_statted_is_not_reported_as_skippable(self, tmp_path):
        """The whole bug in one assertion: the helper must not answer "skip" for a
        file it could not look at, because the caller reads that as deliberate."""
        input_dir = _staging(tmp_path, dangling=("gone.json",))
        item = input_dir / "gone.json"

        with pytest.raises(OSError):
            should_skip_item(item, input_dir, set())

    def test_a_directory_is_still_skipped_silently(self, tmp_path):
        """Control. A directory is a real answer, not a failure to answer, and it
        must not start raising — otherwise every nested folder becomes a loss."""
        input_dir = _staging(tmp_path)
        (input_dir / "nested").mkdir()

        assert should_skip_item(input_dir / "nested", input_dir, set()) is True

    def test_a_dotfile_the_walk_cannot_stat_is_still_just_skipped(self, tmp_path):
        """A deliberate exclusion outranks a failed stat: a dotfile would never be
        processed, so reporting it as a lost record is a false alarm."""
        input_dir = _staging(tmp_path, dangling=(".hidden.json",))

        assert should_skip_item(input_dir / ".hidden.json", input_dir, set()) is True

    def test_a_filtered_suffix_the_walk_cannot_stat_is_still_just_skipped(self, tmp_path):
        """Same reasoning for the suffix filter."""
        input_dir = _staging(tmp_path, dangling=("gone.txt",))

        assert (
            should_skip_item(input_dir / "gone.txt", input_dir, set(), file_type_filter={"json"})
            is True
        )

    def test_an_already_processed_path_the_walk_cannot_stat_is_still_just_skipped(self, tmp_path):
        """And for a path a previous pass already took."""
        input_dir = _staging(tmp_path, dangling=("gone.json",))

        processed = {Path("gone.json")}

        assert should_skip_item(input_dir / "gone.json", input_dir, processed) is True

    def test_a_readable_file_is_still_processed(self, tmp_path):
        """Control: the happy path must not become a loss."""
        input_dir = _staging(tmp_path)

        assert should_skip_item(input_dir / "a.json", input_dir, set()) is False


class TestTheStagingWalkReportsTheLoss:
    """process_directory_files — the record count must go out of service."""

    def _walk(self, tmp_path, backend, *, dangling=("gone.json",), action_config=None):
        input_dir = _staging(tmp_path, names=("a.json", "b.json"), dangling=dangling)
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)
        return process_directory_files(
            runner,
            input_dir,
            tmp_path / "output",
            str(input_dir),
            _params(tmp_path, action_config=action_config),
            set(),
        )

    def test_the_action_count_goes_unknown(self, tmp_path):
        """The consequence the report is about: an action short of a file must not
        keep a count, or a later limit at or above it reads as one that could not
        have bitten and the action is skipped with its short output vouched for."""
        backend = _Backend()

        self._walk(tmp_path, backend)

        assert slice_observation(backend, ACTION) is None

    def test_the_loss_is_recorded_against_the_file(self, tmp_path):
        """Named, so an operator can tell which file went missing."""
        backend = _Backend()

        _found, _processed, errors = self._walk(tmp_path, backend)

        assert any("gone.json" in message for message in errors.messages), errors.messages

    def test_the_walk_still_finishes_the_healthy_files(self, tmp_path):
        """A per-file loss is not fatal to the action — paired with the two above so
        "count is unknown" cannot be satisfied by aborting the whole walk."""
        backend = _Backend()

        _found, processed, _errors = self._walk(tmp_path, backend)

        assert processed == 2

    def test_a_walk_with_nothing_wrong_keeps_its_count(self, tmp_path):
        """Control: the count survives when no file is lost, or the assertion above
        passes for a build that simply poisons every run."""
        backend = _Backend()

        self._walk(tmp_path, backend, dangling=())

        assert slice_observation(backend, ACTION) is not None

    def test_it_says_so_in_the_log(self, tmp_path, caplog):
        """No signal at all is the part that makes this worse than a read failure."""
        backend = _Backend()

        with caplog.at_level("WARNING"):
            self._walk(tmp_path, backend)

        assert "gone.json" in caplog.text


class TestTheLimitStillAnnouncesAShortenedRun:
    """The second reader of ``should_skip_item``: the ``_unread`` closure that
    decides whether a reached limit actually left anything behind. A file it
    cannot stat is not known to be skippable, so it must count as possibly
    unread — otherwise the run stops short and says nothing. Log-only: the
    ``truncated`` flag on the stamp comes from record slicing, not from here.
    """

    def test_a_limit_that_stops_before_an_unstattable_file_says_so(self, tmp_path, caplog):
        input_dir = _staging(tmp_path, names=("a.json",), dangling=("z-gone.json",))
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)

        with caplog.at_level("INFO"):
            process_directory_files(
                runner,
                input_dir,
                tmp_path / "output",
                str(input_dir),
                _params(tmp_path, action_config={"file_limit": 1}),
                set(),
            )

        assert "stopped after 1 file" in caplog.text


class TestTheMergeWalkReportsItToo:
    """``collect_files_from_upstream`` inlines the same three checks, and feeds
    ``process_merged_files``, which counts one file per collected entry. A file
    dropped there is uncounted the same way.
    """

    def test_the_collector_reports_what_it_could_not_stat(self, tmp_path):
        up = _staging(tmp_path, names=("a.json",), dangling=("gone.json",))

        _collected, lost = collect_files_from_upstream([str(up)])

        assert [path.name for path in lost] == ["gone.json"]

    def test_the_collector_still_returns_the_healthy_files(self, tmp_path):
        up = _staging(tmp_path, names=("a.json",), dangling=("gone.json",))

        collected, _lost = collect_files_from_upstream([str(up)])

        assert [path.name for path in collected] == ["a.json"]

    def test_the_merge_walk_puts_the_count_out_of_service(self, tmp_path):
        up = _staging(tmp_path, names=("a.json",), dangling=("gone.json",))
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)

        process_merged_files(runner, _params(tmp_path, upstream_dirs=[str(up)]))

        assert slice_observation(backend, ACTION) is None

    def test_the_merge_walk_keeps_its_count_when_nothing_is_lost(self, tmp_path):
        """Control, as above."""
        up = _staging(tmp_path, names=("a.json",))
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)

        process_merged_files(runner, _params(tmp_path, upstream_dirs=[str(up)]))

        assert slice_observation(backend, ACTION) is not None


class TestWhatStatAsksIsWhatIsFileAsked:
    """The replacement must classify the same things the same way, or the fix
    trades a silent loss for a silent change of what counts as a file.
    """

    def test_a_symlink_to_a_real_file_is_still_a_file(self, tmp_path):
        """``is_file()`` follows links, so ``stat()`` must too — ``lstat`` here would
        start dropping every symlinked input."""
        input_dir = _staging(tmp_path)
        (input_dir / "link.json").symlink_to(input_dir / "a.json")

        assert should_skip_item(input_dir / "link.json", input_dir, set()) is False

    def test_a_fifo_is_not_a_regular_file(self, tmp_path):
        """``is_file()`` is false for a FIFO, which stats fine — so the check has to
        test the mode, not merely that ``stat()`` succeeded."""
        import os

        input_dir = _staging(tmp_path)
        fifo = input_dir / "pipe.json"
        os.mkfifo(fifo)
        assert stat.S_ISFIFO(fifo.stat().st_mode), "precondition: the fixture made a FIFO"

        assert should_skip_item(fifo, input_dir, set()) is True
