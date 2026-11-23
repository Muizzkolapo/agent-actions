"""Storage errors met while a version merge reads its versions.

Verifies that:
- DB errors from list_target_files or read_target fail the merge (not return empty)
- Per-file FileNotFoundError is caught and file skipped
- A DB error when the walk reads a file again fails the merge too
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.workflow.managers.loop import VersionOutputCorrelator
from agent_actions.workflow.managers.output import AllVersionsFilteredError


def _row(guid: str) -> dict:
    return {
        "source_guid": guid,
        "version_correlation_id": f"vc-{guid}",
        "content": {"version_agent_1": {"data": "ok"}},
    }


@pytest.fixture
def loop_manager():
    mgr = VersionOutputCorrelator(Path("/tmp/agent_io"), storage_backend=MagicMock())
    mgr._forget_files_no_version_holds = lambda *args: None  # type: ignore[method-assign]
    return mgr


def _correlate(mgr: VersionOutputCorrelator):
    return mgr.prepare_correlated_input("consumer", ["version_agent_1"], 0)


class TestStorageErrorsWhileCorrelating:
    @pytest.mark.parametrize(
        ("method", "error", "match"),
        [
            pytest.param(
                "list_target_files",
                sqlite3.OperationalError("database is locked"),
                "database is locked",
                id="list_locked",
            ),
            pytest.param(
                "read_target",
                sqlite3.OperationalError("database is locked"),
                "database is locked",
                id="read_locked",
            ),
            pytest.param(
                "read_target",
                json.JSONDecodeError("Expecting value", "", 0),
                "Expecting value",
                id="read_bad_json",
            ),
        ],
    )
    def test_a_storage_error_fails_the_merge(self, loop_manager, method, error, match):
        loop_manager.storage_backend.list_target_files.return_value = ["file_a.json"]
        getattr(loop_manager.storage_backend, method).side_effect = error
        with pytest.raises(ConfigurationError, match=match) as raised:
            _correlate(loop_manager)
        assert raised.value.__cause__ is error

    def test_file_not_found_for_single_file_skips_and_continues(self, loop_manager):
        loop_manager.storage_backend.list_target_files.return_value = ["file_a.json", "file_b.json"]

        def read_target(_version, relative_path):
            if relative_path == "file_a.json":
                raise FileNotFoundError("file_a.json not found")
            return [_row("rec1")]

        loop_manager.storage_backend.read_target.side_effect = read_target
        correlated = _correlate(loop_manager)
        assert list(correlated) == ["file_b.json"]
        assert [row["source_guid"] for row in correlated["file_b.json"]] == ["rec1"]

    def test_no_storage_backend_has_nothing_to_merge(self, loop_manager):
        loop_manager.storage_backend = None
        with pytest.raises(AllVersionsFilteredError):
            _correlate(loop_manager)

    def test_empty_target_files_has_nothing_to_merge(self, loop_manager):
        loop_manager.storage_backend.list_target_files.return_value = []
        with pytest.raises(AllVersionsFilteredError):
            _correlate(loop_manager)

    def test_a_storage_error_when_the_walk_reads_a_file_again_fails_the_merge(self, loop_manager):
        loop_manager.storage_backend.list_target_files.return_value = ["file_a.json"]
        locked = sqlite3.OperationalError("database is locked")
        loop_manager.storage_backend.read_target.side_effect = [[_row("rec1")], locked]
        correlated = _correlate(loop_manager)
        with pytest.raises(ConfigurationError, match="database is locked"):
            correlated["file_a.json"]
