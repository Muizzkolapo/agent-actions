"""Tests for storage error propagation in _load_from_storage_backend.

Verifies that:
- DB errors from list_target_files propagate (not return empty)
- Per-file FileNotFoundError is caught and file skipped
- DB errors from read_target propagate (not silently skipped)
"""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.workflow.managers.loop import VersionOutputCorrelator


@pytest.fixture
def loop_manager():
    mgr = VersionOutputCorrelator.__new__(VersionOutputCorrelator)
    mgr.storage_backend = MagicMock()
    mgr.agent_folder = Path("/tmp/agent_io")
    return mgr


class TestLoadFromStorageBackendErrors:
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
                None,
                id="read_bad_json",
            ),
        ],
    )
    def test_a_storage_error_propagates(self, loop_manager, method, error, match):
        loop_manager.storage_backend.list_target_files.return_value = ["file_a.json"]
        getattr(loop_manager.storage_backend, method).side_effect = error
        with pytest.raises(type(error), match=match):
            loop_manager._load_from_storage_backend("version_agent_1")

    def test_file_not_found_for_single_file_skips_and_continues(self, loop_manager):
        loop_manager.storage_backend.list_target_files.return_value = ["file_a.json", "file_b.json"]
        loop_manager.storage_backend.read_target.side_effect = [
            FileNotFoundError("file_a.json not found"),
            [{"id": "rec1", "data": "ok"}],
        ]
        outputs, filenames = loop_manager._load_from_storage_backend("version_agent_1")
        assert len(outputs) == 1
        assert outputs[0]["id"] == "rec1"
        assert "file_b.json" in filenames
        assert "file_a.json" not in filenames

    def test_no_storage_backend_returns_empty(self, loop_manager):
        loop_manager.storage_backend = None
        outputs, filenames = loop_manager._load_from_storage_backend("version_agent_1")
        assert outputs == []
        assert filenames == set()

    def test_empty_target_files_returns_empty(self, loop_manager):
        loop_manager.storage_backend.list_target_files.return_value = []
        outputs, filenames = loop_manager._load_from_storage_backend("version_agent_1")
        assert outputs == []
        assert filenames == set()
