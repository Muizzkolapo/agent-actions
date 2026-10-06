"""A complete walk deletes what the action stores for an input that is gone (1258).

A reset relies on the re-run writing each file again, and a file whose input was
removed is never written, so its rows stood. The walk is the one place that knows
which inputs it reached, so it deletes the rest once it has reached every input
there is, and only then: a file limit that stopped it, an entry it lost, or a
repair each leave the stored files alone.

Each test's processing writes nothing, as a batch submission does: what is kept
is what the walk can name, not what it happened to rewrite.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import AgentActionsError, DependencyError, mark_action_fatal
from agent_actions.storage.backend import batch_file_names_key
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow import runner_file_processing
from agent_actions.workflow.runner import ActionRunner, FileProcessParams
from agent_actions.workflow.runner_file_processing import process_files

ACTION = "flatten"
UPSTREAM = "extract"


@pytest.fixture(autouse=True)
def _no_ambient_limit(monkeypatch):
    for name in ("AGAC_RECORD_LIMIT", "AGAC_FILE_LIMIT", "AGAC_MAX_RECORDS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
    b.initialize()
    yield b
    b.close()


def _runner(backend, *, fail=()) -> ActionRunner:
    """A runner whose processing stores nothing and fails for the files named."""
    runner = ActionRunner(use_tools=True, storage_backend=backend)

    def process(params):
        if params.locations.item.name in fail:
            raise RuntimeError("down")

    runner._process_single_file = process  # type: ignore[method-assign]
    return runner


def _params(dirs, *, action_config=None) -> FileProcessParams:
    return FileProcessParams(
        action_config=action_config or {},
        action_name=ACTION,
        strategy=MagicMock(),
        upstream_data_dirs=[str(d) for d in dirs],
        output_directory="out",
        idx=0,
    )


def _staged(tmp_path, *names):
    staging = tmp_path / "staging"
    for name in names:
        (staging / name).parent.mkdir(parents=True, exist_ok=True)
        (staging / name).write_text("[]")
    staging.mkdir(exist_ok=True)
    return staging


def _store(backend, *names, action=ACTION):
    for name in names:
        backend._write_target_raw(
            action, name, [{"source_guid": name, "_state": "processed", "_delta_mode": "full"}]
        )


def _held(backend, action=ACTION):
    return backend.list_target_files(action)


def _two_upstreams(tmp_path, *names):
    """Two upstream directories a merged walk reads, each holding *names*."""
    first, second = tmp_path / "first", tmp_path / "second"
    for directory in (first, second):
        directory.mkdir()
        for name in names:
            (directory / name).write_text("[]")
    return first, second


class TestAStagingWalk:
    def test_the_file_of_an_input_that_is_gone_goes(self, backend, tmp_path):
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _held(backend) == ["pages.json"]

    def test_an_input_is_matched_by_its_path_and_the_name_it_is_stored_under(
        self, backend, tmp_path
    ):
        """A first stage stores `notes.csv` as `notes.json`, and a nested file by its path."""
        _store(backend, "notes.json", "sub/pages.json", "pages.json", "sub/gone.json")

        process_files(_runner(backend), _params([_staged(tmp_path, "notes.csv", "sub/pages.json")]))

        assert _held(backend) == ["notes.json", "sub/pages.json"]

    def test_an_input_is_matched_by_the_name_the_store_gives_it(self, backend, tmp_path):
        """The store strips the whitespace around a name and turns a backslash into a slash."""
        _store(backend, " lead.json", "export\\part.json", "gone.json")

        process_files(
            _runner(backend), _params([_staged(tmp_path, " lead.json", "export\\part.json")])
        )

        assert _held(backend) == ["export/part.json", "lead.json"]

    def test_a_file_that_failed_keeps_its_rows(self, backend, tmp_path):
        _store(backend, "broken.json", "gone.json", "pages.json")

        process_files(
            _runner(backend, fail={"broken.json"}),
            _params([_staged(tmp_path, "broken.json", "pages.json")]),
        )

        assert _held(backend) == ["broken.json", "pages.json"]

    def test_a_walk_where_every_file_failed_deletes_nothing(self, backend, tmp_path):
        """It raises, and a walk that raised has said nothing about what is gone."""
        _store(backend, "gone.json", "pages.json")

        with pytest.raises(DependencyError):
            process_files(
                _runner(backend, fail={"pages.json"}), _params([_staged(tmp_path, "pages.json")])
            )

        assert _held(backend) == ["gone.json", "pages.json"]

    def test_a_walk_that_lost_an_entry_deletes_nothing(self, backend, tmp_path):
        """It cannot say which inputs are gone."""
        staging = _staged(tmp_path, "pages.json")
        (staging / "dangling.json").symlink_to(staging / "nowhere.json")
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params([staging]))

        assert _held(backend) == ["gone.json", "pages.json"]

    def test_a_walk_that_could_not_list_a_directory_deletes_nothing(
        self, backend, tmp_path, monkeypatch
    ):
        """What lay beneath it may still be there."""
        staging = _staged(tmp_path, "pages.json")
        _store(backend, "gone.json", "pages.json", "sub/kept.json")
        walk_files = runner_file_processing.walk_files

        def walk(root, on_error):
            on_error(PermissionError(13, "Permission denied", str(root / "sub")))
            return walk_files(root, on_error)

        monkeypatch.setattr(runner_file_processing, "walk_files", walk)

        process_files(_runner(backend), _params([staging]))

        assert _held(backend) == ["gone.json", "pages.json", "sub/kept.json"]

    def test_a_file_limit_that_stops_the_walk_deletes_nothing(self, backend, tmp_path):
        """A file it never opened keeps what the last run put there, on purpose."""
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend),
            _params([_staged(tmp_path, "a.json", "b.json")], action_config={"file_limit": 1}),
        )

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_file_limit_reached_on_the_last_file_left_still_deletes(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend),
            _params([_staged(tmp_path, "a.json", "b.json")], action_config={"file_limit": 2}),
        )

        assert _held(backend) == ["a.json", "b.json"]

    def test_a_repair_deletes_nothing(self, backend, tmp_path):
        """It touches only the records it named."""
        _store(backend, "gone.json", "pages.json")
        runner = _runner(backend)
        runner.retried_records = frozenset({"g0"})

        process_files(runner, _params([_staged(tmp_path, "pages.json")]))

        assert _held(backend) == ["gone.json", "pages.json"]

    def test_a_warning_names_the_files_deleted(self, backend, tmp_path, caplog):
        """A reset that a flag set off can delete stored output; the user hears which."""
        _store(backend, "gone.json", "pages.json")

        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert "gone.json" in warning.getMessage()
        assert "pages.json" not in warning.getMessage()

    def test_a_warning_names_a_few_of_many_files_deleted_and_counts_the_rest(
        self, backend, tmp_path, caplog
    ):
        """It is logged for every action that reads the input, so it stays one line."""
        _store(backend, *(f"gone_{n}.json" for n in range(5)), "pages.json")

        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert "gone_0.json, gone_1.json, gone_2.json (and 2 more)" in warning.getMessage()
        assert "gone_3.json" not in warning.getMessage()
        assert _held(backend) == ["pages.json"]

    def test_a_delete_that_fails_only_warns(self, backend, tmp_path, monkeypatch, caplog):
        _store(backend, "gone.json", "pages.json")

        def refuse(*_args):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(backend, "delete_target_files", refuse)
        with caplog.at_level(logging.WARNING, logger=runner_file_processing.__name__):
            process_files(_runner(backend), _params([_staged(tmp_path, "pages.json")]))

        assert _held(backend) == ["gone.json", "pages.json"]
        assert "database is locked" in caplog.text


class TestABatchInputFile:
    def test_the_name_recorded_for_a_nested_file_is_kept(self, backend, tmp_path):
        """A store from an older version holds `sub/pages.json` under its basename."""
        backend.save_metadata(
            batch_file_names_key(ACTION),
            json.dumps({"sub/pages.json": "pages.json", "old/gone.json": "gone.json"}),
        )
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params([_staged(tmp_path, "sub/pages.json")]))

        assert _held(backend) == ["pages.json"]

    def test_the_name_recorded_for_an_input_that_is_gone_is_forgotten(self, backend, tmp_path):
        """It names rows that are gone; left, the input coming back would take a name
        nothing holds any more."""
        backend.save_metadata(
            batch_file_names_key(ACTION),
            json.dumps({"sub/pages.json": "pages.json", "old/gone.json": "gone.json"}),
        )
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params([_staged(tmp_path, "sub/pages.json")]))

        assert json.loads(backend.load_metadata(batch_file_names_key(ACTION))) == {
            "sub/pages.json": "pages.json"
        }

    def test_the_name_recorded_for_a_nested_file_is_matched_as_the_store_lists_it(
        self, backend, tmp_path
    ):
        """Its basename ` pages.json` was stored as `pages.json`."""
        backend.save_metadata(
            batch_file_names_key(ACTION), json.dumps({"sub/ pages.json": " pages.json"})
        )
        _store(backend, " pages.json", "gone.json")

        process_files(_runner(backend), _params([_staged(tmp_path, "sub/ pages.json")]))

        assert _held(backend) == ["pages.json"]

    def test_the_name_recorded_for_a_nested_file_of_another_type_is_kept_as_json(
        self, backend, tmp_path
    ):
        """`sub/notes.csv` recorded as `notes.csv` is stored as `notes.json`."""
        backend.save_metadata(
            batch_file_names_key(ACTION), json.dumps({"sub/notes.csv": "notes.csv"})
        )
        _store(backend, "gone.json", "notes.json")

        process_files(_runner(backend), _params([_staged(tmp_path, "sub/notes.csv")]))

        assert _held(backend) == ["notes.json"]


class TestAStorageWalk:
    def test_a_reader_lets_go_of_a_file_its_upstream_no_longer_holds(self, backend, tmp_path):
        _store(backend, "pages.json", action=UPSTREAM)
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params([tmp_path / "target" / UPSTREAM]))

        assert _held(backend) == ["pages.json"]

    def test_a_file_that_failed_keeps_its_rows(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", action=UPSTREAM)
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(_runner(backend, fail={"b.json"}), _params([tmp_path / "target" / UPSTREAM]))

        assert _held(backend) == ["a.json", "b.json"]

    def test_a_file_limit_that_stops_the_walk_deletes_nothing(self, backend, tmp_path):
        """`--file-limit` stops a reader as it stops a first stage."""
        _store(backend, "a.json", "b.json", action=UPSTREAM)
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend),
            _params([tmp_path / "target" / UPSTREAM], action_config={"file_limit": 1}),
        )

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_stored_file_it_could_not_read_keeps_everything(self, backend, tmp_path, monkeypatch):
        _store(backend, "a.json", "b.json", action=UPSTREAM)
        _store(backend, "a.json", "b.json", "gone.json")
        read = backend.read_target

        def read_target(action_name, relative_path):
            if action_name == UPSTREAM and relative_path == "b.json":
                raise sqlite3.OperationalError("disk I/O error")
            return read(action_name, relative_path)

        monkeypatch.setattr(backend, "read_target", read_target)

        process_files(_runner(backend), _params([tmp_path / "target" / UPSTREAM]))

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_walk_an_action_fatal_error_stopped_deletes_nothing(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", action=UPSTREAM)
        _store(backend, "a.json", "b.json", "gone.json")
        runner = _runner(backend)

        def process(params):
            if params.locations.item.name == "b.json":
                raise mark_action_fatal(AgentActionsError("provider refused the key"))

        runner._process_single_file = process  # type: ignore[method-assign]

        with pytest.raises(DependencyError):
            process_files(runner, _params([tmp_path / "target" / UPSTREAM]))

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_version_merge_walking_its_own_files_deletes_none(self, backend, tmp_path):
        """Its correlated input is stored under its own name, and that is what it walks."""
        _store(backend, "a.json", "b.json")

        process_files(_runner(backend), _params([tmp_path / "target" / ACTION]))

        assert _held(backend) == ["a.json", "b.json"]

    def test_an_upstream_it_could_not_list_keeps_everything(self, backend, tmp_path, monkeypatch):
        other = "lister"
        _store(backend, "pages.json", action=UPSTREAM)
        _store(backend, "gone.json", "pages.json")
        listed = backend.list_target_files

        def list_target_files(action_name):
            if action_name == other:
                raise sqlite3.OperationalError("disk I/O error")
            return listed(action_name)

        monkeypatch.setattr(backend, "list_target_files", list_target_files)
        dirs = [tmp_path / "target" / UPSTREAM, tmp_path / "target" / other]

        process_files(_runner(backend), _params(dirs))

        assert listed(ACTION) == ["gone.json", "pages.json"]


class TestAMergedWalk:
    def test_the_file_of_an_input_no_upstream_holds_goes(self, backend, tmp_path):
        _store(backend, "gone.json", "pages.json")

        process_files(_runner(backend), _params(_two_upstreams(tmp_path, "pages.json")))

        assert _held(backend) == ["pages.json"]

    def test_a_file_that_failed_keeps_its_rows(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend, fail={"b.json"}),
            _params(_two_upstreams(tmp_path, "a.json", "b.json")),
        )

        assert _held(backend) == ["a.json", "b.json"]

    def test_a_file_limit_that_stops_the_walk_deletes_nothing(self, backend, tmp_path):
        _store(backend, "a.json", "b.json", "gone.json")

        process_files(
            _runner(backend),
            _params(_two_upstreams(tmp_path, "a.json", "b.json"), action_config={"file_limit": 1}),
        )

        assert _held(backend) == ["a.json", "b.json", "gone.json"]

    def test_a_walk_that_lost_an_entry_deletes_nothing(self, backend, tmp_path):
        first, second = _two_upstreams(tmp_path, "a.json")
        (first / "dangling.json").symlink_to(first / "nowhere.json")
        _store(backend, "a.json", "gone.json")

        process_files(_runner(backend), _params([first, second]))

        assert _held(backend) == ["a.json", "gone.json"]
