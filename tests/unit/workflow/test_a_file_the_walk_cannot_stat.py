"""A staged file the filesystem will not describe is a loss, not a skip (1026).

``Path.is_file()`` answers ``False`` for ``ENOENT``/``ENOTDIR``/``EBADF``/``ELOOP``,
so a dangling symlink reads as a directory and the walk drops it — without the
``_lose_file`` and the found-count every other per-file failure makes, which leaves
an all-lost walk completing green and empty. A permission failure was never silent:
``is_file()`` re-raises it mid-walk with no file attached, and it is folded into the
same named loss here.
"""

import contextlib
import errno
import json
import logging
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import DependencyError
from agent_actions.utils.limits import record_indices_to_process, slice_observation
from agent_actions.workflow import runner_file_processing
from agent_actions.workflow.runner_file_processing import (
    collect_files_from_upstream,
    process_directory_files,
    process_files,
    process_merged_files,
    should_skip_item,
)

ACTION = "flatten"
WALK_LOGGER = runner_file_processing.__name__


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


@contextlib.contextmanager
def _walk_log(caplog):
    """`caplog` with the walk's own logger lowered, so its records actually arrive.

    `at_level` raises the level of the logger it is *given* — the root when omitted —
    and an effective level resolves through the nearest ancestor that sets one, so an
    `agent_actions` WARNING left behind by another test blinds every level assertion
    here, and the two that assert an *absence* would pass while proving nothing. The
    name comes from the module under test rather than a literal: a mistyped one makes a
    fresh logger at the requested level and leaves the real one suppressed, silently,
    for that one test.
    """
    with caplog.at_level(logging.DEBUG, logger=WALK_LOGGER):
        yield caplog


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    """Clear the limits an ambient export could impose, including the file limit.

    The tests exposed to `AGAC_FILE_LIMIT` are the ones passing no `file_limit` at all:
    `_resolve` returns the config value whenever it is set and not greater than the
    override, so a test asking for 1 was already immune. `AGAC_MAX_RECORDS` is the
    retired name, cleared so a stale export cannot trip the retirement path.
    """
    for name in ("AGAC_RECORD_LIMIT", "AGAC_FILE_LIMIT", "AGAC_MAX_RECORDS"):
        monkeypatch.delenv(name, raising=False)


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
        target = input_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(input_dir / "does-not-exist.json")
    (tmp_path / "output").mkdir(exist_ok=True)
    return input_dir


def _unreadable(input_dir, name="locked/denied.json"):
    """A real file whose parent directory denies traversal, so ``stat()`` is EACCES.

    ``rglob`` still lists it at mode 0o444, which is what makes this reach the walk
    at all. Returned so the caller can restore the mode; pytest cannot clean up a
    directory it may not enter.
    """
    target = input_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("[]")
    target.parent.chmod(0o444)
    return target.parent


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
        """Named by the path the walk resolved, not merely mentioned.

        Asserted as a prefix of the message rather than a substring: ``str(OSError)``
        from a failed ``stat()`` embeds the absolute path, so "the file's name appears
        somewhere" is satisfied by the exception's own text even when the loss is
        recorded against a completely different file.
        """
        backend = _Backend()

        _found, _processed, errors = self._walk(tmp_path, backend, dangling=("sub/gone.json",))

        assert any(m.startswith("sub/gone.json:") for m in errors.messages), errors.messages

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

        with _walk_log(caplog):
            self._walk(tmp_path, backend, dangling=("sub/gone.json",))

        assert "staged file sub/gone.json" in caplog.text, caplog.text


class TestAWalkThatLosesEverything:
    """The case the report is actually about, and the one the first fix missed.

    ``process_files`` raises only when ``files_found > 0``; with nothing found it
    warns instead, and ``warn_no_files_found`` stays quiet because the directory
    does have content. So a lost file has to count as found, exactly as a file that
    fails while being read does — otherwise a walk whose every entry was unreadable
    completes green with no output, which is the silence under repair.
    """

    def _run(self, tmp_path, backend, *, names=(), dangling=("gone.json",)):
        input_dir = _staging(tmp_path, names=names, dangling=dangling)
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)
        return process_directory_files(
            runner, input_dir, tmp_path / "output", str(input_dir), _params(tmp_path), set()
        )

    def test_a_lost_file_counts_as_found(self, tmp_path):
        found, processed, _errors = self._run(tmp_path, _Backend())

        assert (found, processed) == (1, 0)

    def test_a_file_that_fails_while_being_read_counts_the_same_way(self, tmp_path):
        """The equivalence the code comment claims. Pinned, because the first
        version of this fix asserted it in a comment while breaking it."""
        backend = _Backend()
        input_dir = _staging(tmp_path, names=("a.json",))
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = ValueError("unreadable input")

        found, processed, _errors = process_directory_files(
            runner, input_dir, tmp_path / "output", str(input_dir), _params(tmp_path), set()
        )

        assert (found, processed) == (1, 0)

    def test_the_merge_walk_counts_a_lost_file_as_found_too(self, tmp_path):
        up = _staging(tmp_path, names=(), dangling=("gone.json",))
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)

        found, processed, _errors = process_merged_files(
            runner, _params(tmp_path, upstream_dirs=[str(up)])
        )

        assert (found, processed) == (1, 0)


class TestAnErrnoOtherThanEnoent:
    """``is_file()`` hides only ENOENT, ENOTDIR, EBADF and ELOOP; it re-raises the
    rest, so EACCES already escaped — from the middle of a walk, as an error with
    no file attached. Catching ``OSError`` here is deliberately wider than the
    silent set, which turns that into the same named, counted loss.

    Without this, narrowing the handler to ``except FileNotFoundError`` passes the
    whole suite while restoring the unattributed failure for the cause the report
    names first.
    """

    def test_a_permission_failure_is_reported_like_any_other_loss(self, tmp_path):
        input_dir = _staging(tmp_path, names=("a.json",))
        locked = _unreadable(input_dir)
        try:
            backend = _Backend()
            runner = MagicMock()
            runner.retried_records = frozenset()
            runner.storage_backend = backend
            runner._process_single_file.side_effect = _slices(backend)

            found, processed, errors = process_directory_files(
                runner, input_dir, tmp_path / "output", str(input_dir), _params(tmp_path), set()
            )
        finally:
            locked.chmod(0o755)

        assert (found, processed) == (2, 1), "the readable file still ran; the locked one counted"
        assert any(f"[Errno {errno.EACCES}]" in m for m in errors.messages), errors.messages
        assert slice_observation(backend, ACTION) is None

    def test_the_collector_hands_back_the_permission_errno(self, tmp_path):
        up = _staging(tmp_path, names=("a.json",))
        locked = _unreadable(up)
        try:
            _collected, lost = collect_files_from_upstream([str(up)])
        finally:
            locked.chmod(0o755)

        assert [e.errno for _path, e in lost] == [errno.EACCES], lost


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

        with _walk_log(caplog):
            process_directory_files(
                runner,
                input_dir,
                tmp_path / "output",
                str(input_dir),
                _params(tmp_path, action_config={"file_limit": 1}),
                set(),
            )

        assert "stopped after 1 file" in caplog.text


class TestALostFileDoesNotSilenceTheLimit:
    """Counting a loss as found gave ``files_seen`` two readers with two questions:
    the caller's "how many were found", and the limit probe's "how far through the
    groups am I". Compared against the group total, a loss-inclusive count suppresses
    the truncation announcement by exactly the number of losses — a walk stopping
    short of a file while saying nothing, which is the failure this branch removes.
    """

    def _merge(self, tmp_path, *, dangling, good, limit):
        up = tmp_path / "up"
        up.mkdir(parents=True, exist_ok=True)
        for i in range(good):
            (up / f"good{i}.json").write_text(json.dumps([{"id": i}]))
        for i in range(dangling):
            (up / f"gone{i}.json").symlink_to(up / f"missing{i}.json")
        (tmp_path / "output").mkdir(exist_ok=True)
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)
        return process_merged_files(
            runner,
            _params(tmp_path, upstream_dirs=[str(up)], action_config={"file_limit": limit}),
        )

    def test_a_truncated_merge_still_says_so_when_a_file_was_lost(self, tmp_path, caplog):
        with _walk_log(caplog):
            self._merge(tmp_path, dangling=1, good=2, limit=1)

        assert "stopped after 1 file" in caplog.text, caplog.text

    def test_the_same_walk_without_a_loss_still_says_so(self, tmp_path, caplog):
        """Control: isolates the loss as the cause rather than the limit."""
        with _walk_log(caplog):
            self._merge(tmp_path, dangling=0, good=2, limit=1)

        assert "stopped after 1 file" in caplog.text, caplog.text

    def test_a_limit_that_reached_every_group_stays_quiet(self, tmp_path, caplog):
        """And the announcement is not simply always made.

        The loss warning is asserted first because this test's real assertion is an
        absence: capture that silently saw nothing would satisfy it while proving
        nothing. The same walk must emit that warning, so it doubles as evidence the
        records reached ``caplog`` at all.
        """
        with _walk_log(caplog):
            self._merge(tmp_path, dangling=1, good=1, limit=1)

        assert "went unmerged" in caplog.text, f"nothing captured: {caplog.text!r}"
        assert "stopped after" not in caplog.text, caplog.text

    def test_a_group_that_failed_is_not_reported_as_one_left_behind(self, tmp_path, caplog):
        """The mirror image: `groups_seen` must count a group the walk *attempted*, not
        one it merged, or a failed merge reads as a limit that cut the run short and
        sends an operator to raise the limit instead of investigating the failure.
        """
        up = tmp_path / "up"
        up.mkdir(parents=True)
        for i in range(2):
            (up / f"good{i}.json").write_text(json.dumps([{"id": i}]))
        (tmp_path / "output").mkdir()
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        # The first group fails and the second succeeds, so the limit is actually
        # reached and `_unread` is actually consulted. With every group failing the
        # walk never reaches the limit and this asserts nothing about `groups_seen`.
        runner._process_single_file.side_effect = [ValueError("merge failed"), None]

        with _walk_log(caplog):
            found, processed, _errors = process_merged_files(
                runner,
                _params(tmp_path, upstream_dirs=[str(up)], action_config={"file_limit": 1}),
            )

        assert (found, processed) == (2, 1), "both groups attempted, one merged"
        assert "merge failed" in caplog.text, f"nothing captured: {caplog.text!r}"
        assert "stopped after" not in caplog.text, caplog.text

    def test_a_failed_group_does_not_hide_one_the_limit_did_leave(self, tmp_path, caplog):
        """The other side: with a third group the limit genuinely cuts the run short,
        and the failure must not suppress the announcement."""
        up = tmp_path / "up"
        up.mkdir(parents=True)
        for i in range(3):
            (up / f"good{i}.json").write_text(json.dumps([{"id": i}]))
        (tmp_path / "output").mkdir()
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = [ValueError("merge failed"), None]

        with _walk_log(caplog):
            process_merged_files(
                runner,
                _params(tmp_path, upstream_dirs=[str(up)], action_config={"file_limit": 1}),
            )

        assert caplog.text.count("stopped after") == 1, caplog.text


class TestALostUpstreamFileIsNamedByItsGroupPath:
    """``_upstream_relative`` exists so a lost file is keyed like every other record
    in the merge walk. Staged at the top level its answer and its basename coincide,
    so the helper is only pinned by a file in a subdirectory.
    """

    def test_the_subdirectory_survives_into_the_recorded_key(self, tmp_path):
        up = tmp_path / "up"
        (up / "sub").mkdir(parents=True)
        (up / "sub" / "gone.json").symlink_to(up / "sub" / "missing.json")
        (up / "ok.json").write_text(json.dumps([{"id": 1}]))
        (tmp_path / "output").mkdir()
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)

        _found, _processed, errors = process_merged_files(
            runner, _params(tmp_path, upstream_dirs=[str(up)])
        )

        assert any(m.startswith("sub/gone.json:") for m in errors.messages), errors.messages


class TestTheGuaranteeWhereItActuallyLives:
    """``(found, processed) == (1, 0)`` from the walker is the mechanism; the promise
    is that ``process_files`` then fails rather than completing green and empty. That
    coupling is the thing a later change could break while the walker's numbers stay
    right, so it is asserted here through ``process_files`` itself.
    """

    def _run(self, tmp_path, *, names, dangling):
        up = _staging(tmp_path, names=names, dangling=dangling)
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)
        params = _params(tmp_path, upstream_dirs=[str(up)])
        process_files(runner, params)
        return backend

    def test_a_walk_that_lost_everything_fails_the_action(self, tmp_path):
        with pytest.raises(DependencyError, match="gone.json"):
            self._run(tmp_path, names=(), dangling=("gone.json",))

    def test_a_walk_that_lost_only_some_completes(self, tmp_path):
        """Paired with it: a per-file loss is not fatal, so the raise above must not
        come from "any loss at all"."""
        self._run(tmp_path, names=("a.json",), dangling=("gone.json",))

    def test_the_completing_walk_still_has_its_count_taken_out_of_service(self, tmp_path):
        """The backend this class wires is real, so it should be asked something."""
        backend = self._run(tmp_path, names=("a.json",), dangling=("gone.json",))

        assert slice_observation(backend, ACTION) is None


class TestTheMergeWalkReportsItToo:
    """``collect_files_from_upstream`` inlines the same three checks, and feeds
    ``process_merged_files``, which counts one file per collected entry. A file
    dropped there is uncounted the same way.
    """

    def test_the_collector_reports_what_it_could_not_stat(self, tmp_path):
        up = _staging(tmp_path, names=("a.json",), dangling=("gone.json",))

        _collected, lost = collect_files_from_upstream([str(up)])

        assert [path.name for path, _error in lost] == ["gone.json"]

    def test_the_collector_hands_back_why_it_could_not(self, tmp_path):
        """Paired with the test above: the staging walk records the real exception,
        so the merge walk must too. A bare list of paths tells an operator a file
        went missing without saying whether it was a permission or a missing target,
        which is the diagnostic half of the same silence this fixes.
        """
        up = _staging(tmp_path, names=("a.json",), dangling=("gone.json",))

        _collected, lost = collect_files_from_upstream([str(up)])

        assert lost[0][1].errno == errno.ENOENT, lost[0][1]

    def test_the_merge_walk_names_the_reason_in_its_error(self, tmp_path):
        """And the reason survives into the action's collected errors, not just the log."""
        up = _staging(tmp_path, names=("a.json",), dangling=("gone.json",))
        backend = _Backend()
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend = backend
        runner._process_single_file.side_effect = _slices(backend)

        _found, _processed, errors = process_merged_files(
            runner, _params(tmp_path, upstream_dirs=[str(up)])
        )

        assert any(f"[Errno {errno.ENOENT}]" in m for m in errors.messages), errors.messages

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
