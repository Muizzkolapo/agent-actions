"""An all-lost backend walk must fail the action, not finish green and empty.

`process_from_storage_backend` computed its found-count from what it managed to read
(`len(data_by_path)`), so an entry lost to a failed listing or read was absent from the
count AND from `CollectedErrors`. With nothing found, `process_files`' `files_found > 0`
gate never fired, and the action completed as though its input had never existed.

#1026 fixed the same defect for the two filesystem walks; this is the third walker.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

from agent_actions.workflow.runner import FileProcessParams
from agent_actions.workflow.runner_file_processing import process_from_storage_backend


def _params(tmp_path: Path, upstreams=("a1",)) -> FileProcessParams:
    dirs = []
    for name in upstreams:
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        dirs.append(str(d))
    return FileProcessParams(
        action_config={},
        action_name="b",
        strategy=MagicMock(),
        upstream_data_dirs=dirs,
        output_directory=str(tmp_path / "out"),
        idx=0,
    )


def _runner(*, listing=None, reading=None, files=("r1.json", "r2.json")):
    runner = MagicMock()
    runner.storage_backend = MagicMock()
    if listing is not None:
        runner.storage_backend.list_target_files.side_effect = listing
    else:
        runner.storage_backend.list_target_files.return_value = list(files)
    if reading is not None:
        runner.storage_backend.read_target.side_effect = reading
    return runner


class TestALostEntryIsCountedAndNamed:
    def test_a_failed_listing_is_counted_as_found(self, tmp_path):
        """Otherwise (0, 0) skips the gate that raises, and the run reports success."""
        found, processed, errors = process_from_storage_backend(
            _runner(listing=sqlite3.Error("backend down")), _params(tmp_path)
        )

        assert processed == 0
        assert found > 0, "a lost upstream must count as found or nothing raises"

    def test_a_failed_listing_is_recorded_so_the_failure_names_it(self, tmp_path):
        _, _, errors = process_from_storage_backend(
            _runner(listing=sqlite3.Error("backend down")), _params(tmp_path)
        )

        assert errors.messages, "the loss must reach CollectedErrors to be reported"
        assert any("a1" in m and "backend down" in m for m in errors.messages), errors.messages

    def test_a_failed_read_is_counted_as_found(self, tmp_path):
        found, processed, _ = process_from_storage_backend(
            _runner(reading=sqlite3.Error("row gone")), _params(tmp_path)
        )

        assert processed == 0
        assert found == 2, f"both unreadable entries must be counted, got {found}"

    def test_a_failed_read_names_each_lost_entry(self, tmp_path):
        _, _, errors = process_from_storage_backend(
            _runner(reading=sqlite3.Error("row gone")), _params(tmp_path)
        )

        assert any("r1.json" in m for m in errors.messages), errors.messages
        assert any("r2.json" in m for m in errors.messages), errors.messages

    def test_a_partial_loss_counts_both_the_read_and_the_lost(self, tmp_path):
        """The count has to be found-not-processed, or a partial failure looks complete."""
        runner = _runner(reading=[{"content": {}}, sqlite3.Error("row gone")])
        found, _, errors = process_from_storage_backend(runner, _params(tmp_path))

        assert found == 2, f"one read + one lost is still two entries, got {found}"
        assert any("r2.json" in m for m in errors.messages), errors.messages


class TestAHealthyWalkIsUnchanged:
    def test_nothing_lost_counts_only_what_was_read(self, tmp_path):
        runner = _runner(reading=[{"content": {}}, {"content": {}}])
        found, _, errors = process_from_storage_backend(runner, _params(tmp_path))

        assert found == 2
        assert errors.messages == []

    def test_an_empty_backend_still_reports_nothing_found(self, tmp_path):
        """(0, 0) with no losses is the honest 'there was no input' case, which must
        keep falling through rather than raising."""
        runner = _runner(files=())
        found, processed, errors = process_from_storage_backend(runner, _params(tmp_path))

        assert (found, processed) == (0, 0)
        assert errors.messages == []


class TestTheActionActuallyFails:
    """The walker's count only matters if it reaches process_files' gate.

    These call process_files, not the walker: upstream dirs must satisfy
    is_target_directory (a parent named "target") or the storage branch is
    skipped entirely and the walker is never consulted.
    """

    @staticmethod
    def _target_params(tmp_path: Path) -> FileProcessParams:
        up = tmp_path / "agent_io" / "target" / "a1"
        up.mkdir(parents=True)
        return FileProcessParams(
            action_config={},
            action_name="b",
            strategy=MagicMock(),
            upstream_data_dirs=[str(up)],
            output_directory=str(tmp_path / "out"),
            idx=0,
        )

    def test_an_all_lost_listing_raises_and_names_the_upstream(self, tmp_path):
        import pytest

        from agent_actions.errors import DependencyError
        from agent_actions.workflow.runner_file_processing import process_files

        with pytest.raises(DependencyError) as excinfo:
            process_files(
                _runner(listing=sqlite3.Error("backend down")), self._target_params(tmp_path)
            )

        assert "a1" in str(excinfo.value)
        assert "backend down" in str(excinfo.value)

    def test_an_all_lost_read_raises_and_names_every_entry(self, tmp_path):
        import pytest

        from agent_actions.errors import DependencyError
        from agent_actions.workflow.runner_file_processing import process_files

        with pytest.raises(DependencyError) as excinfo:
            process_files(_runner(reading=sqlite3.Error("row gone")), self._target_params(tmp_path))

        message = str(excinfo.value)
        assert "r1.json" in message and "r2.json" in message, message

    def test_a_genuinely_empty_backend_is_not_reported_as_unreadable(self, tmp_path):
        """'there was no input' must stay distinguishable from 'none of it could be read'."""
        import pytest

        from agent_actions.workflow.runner_file_processing import NoInputFilesError, process_files

        runner = _runner(files=())
        runner.retried_records = frozenset()

        with pytest.raises(NoInputFilesError):
            process_files(runner, self._target_params(tmp_path))
