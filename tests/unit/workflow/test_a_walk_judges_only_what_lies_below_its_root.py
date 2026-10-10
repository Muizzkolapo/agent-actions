"""A walk judges a path by what lies below the directory it walks, not above it.

Testing "staging" or "batch" against the absolute path let the directories a
project sits under decide what the walk read: under `staging-env/` an upstream's
stored rows were never consulted, and under `batch/` every staged file was left
out. Finding nothing now skips the action and deletes its rows, so either one
cost stored output.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agent_actions.workflow import runner_file_processing
from agent_actions.workflow.runner import ActionRunner, FileProcessParams
from agent_actions.workflow.runner_file_processing import (
    _walk_files,
    collect_files_from_upstream,
    is_target_directory,
    process_files,
)


def _params(dirs, strategy=None) -> FileProcessParams:
    return FileProcessParams(
        action_config={},
        action_name="flatten",
        strategy=strategy or MagicMock(),
        upstream_data_dirs=[str(d) for d in dirs],
        output_directory="out",
        idx=0,
    )


def _staged(directory: Path) -> Path:
    directory.mkdir(parents=True)
    (directory / "pages.json").write_text("[]")
    return directory


class TestAProjectUnderADirectoryNamedBatch:
    def test_its_staged_file_is_processed(self, tmp_path):
        staging = _staged(tmp_path / "batch" / "project" / "agent_io" / "staging")
        strategy = MagicMock()

        process_files(ActionRunner(use_tools=True), _params([staging], strategy))

        strategy.execute.assert_called_once()

    def test_a_merged_walk_groups_its_files(self, tmp_path):
        upstreams = [_staged(tmp_path / "batch" / "target" / name) for name in ("a", "b")]

        grouped, lost = collect_files_from_upstream([str(d) for d in upstreams])

        assert list(grouped) == [Path("pages.json")]
        assert lost == []

    def test_a_directory_it_cannot_open_is_still_reported(self, tmp_path, monkeypatch):
        root = tmp_path / "batch" / "staging"
        failure = OSError(13, "Permission denied", str(root / "sub"))

        def _walk(_root, on_error):
            on_error(failure)
            return []

        monkeypatch.setattr(runner_file_processing, "walk_files", _walk)
        unreadable: list = []

        _walk_files(root, unreadable)

        assert unreadable == [(root / "sub", failure)]


class TestABatchDirectoryInsideTheWalk:
    def test_is_still_left_out(self, tmp_path):
        staging = _staged(tmp_path / "staging")
        _staged(staging / "batch")
        strategy = MagicMock()

        process_files(ActionRunner(use_tools=True), _params([staging], strategy))

        assert strategy.execute.call_count == 1
        assert strategy.execute.call_args.args[0].file_path == str(staging / "pages.json")

    def test_an_unopened_one_is_not_reported(self, tmp_path, monkeypatch):
        root = tmp_path / "staging"

        def _walk(_root, on_error):
            on_error(OSError(13, "Permission denied", str(root / "batch")))
            return []

        monkeypatch.setattr(runner_file_processing, "walk_files", _walk)
        unreadable: list = []

        _walk_files(root, unreadable)

        assert unreadable == []


class TestAProjectUnderADirectoryNamedStaging:
    def test_an_upstream_output_is_a_target_directory(self):
        assert is_target_directory("/srv/staging-env/project/agent_io/target/flatten")

    def test_staged_input_is_not(self):
        assert not is_target_directory("/srv/target/project/agent_io/staging")

    def test_an_upstream_is_read_from_the_store(self, tmp_path):
        upstream = tmp_path / "staging-env" / "project" / "agent_io" / "target" / "a1"
        runner = MagicMock()
        runner.retried_records = frozenset()
        runner.storage_backend.list_target_files.return_value = ["pages.json"]
        runner.storage_backend.read_target.return_value = [{"content": {}}]

        process_files(runner, _params([upstream]))

        runner.storage_backend.list_target_files.assert_any_call("a1")
        runner._process_single_file.assert_called_once()
