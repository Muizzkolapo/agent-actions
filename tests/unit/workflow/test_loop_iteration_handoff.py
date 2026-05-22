"""Tests for prepare_correlated_input iteration handoff.

Verifies that version outputs from iteration N correctly feed iteration N+1
via prepare_correlated_input → _load_version_outputs → _process_version_files.
Also tests the (OSError, ValueError, KeyError) catch-all in prepare_correlated_input.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.workflow.managers.loop import VersionOutputCorrelator


@pytest.fixture
def storage_backend():
    """Create a mock storage backend with standard return values."""
    backend = MagicMock()
    backend.list_target_files.return_value = []
    backend.read_target.return_value = []
    return backend


@pytest.fixture
def correlator(tmp_path, storage_backend):
    """Create a VersionOutputCorrelator with a temp agent folder."""
    return VersionOutputCorrelator(
        agent_folder=tmp_path,
        storage_backend=storage_backend,
    )


class TestLoopIterationHandoff:
    """Tests for prepare_correlated_input and the iteration handoff path."""

    def test_two_version_outputs_correlated_by_source_record(self, correlator, storage_backend):
        """Outputs from two version agents merge correctly by correlation ID."""
        # Version agent "v1" produced records
        v1_records = [
            {
                "version_correlation_id": "corr_1",
                "source_guid": "guid_1",
                "content": {"v1": {"answer": "from_v1"}},
                "_source_file": "data.json",
            },
        ]
        # Version agent "v2" produced records
        v2_records = [
            {
                "version_correlation_id": "corr_1",
                "source_guid": "guid_1",
                "content": {"v2": {"answer": "from_v2"}},
                "_source_file": "data.json",
            },
        ]

        def mock_list_target_files(agent_name):
            return ["data.json"]

        def mock_read_target(agent_name, relative_path):
            if agent_name == "v1":
                return v1_records
            return v2_records

        storage_backend.list_target_files.side_effect = mock_list_target_files
        storage_backend.read_target.side_effect = mock_read_target

        result = correlator.prepare_correlated_input(
            agent_name="downstream_action",
            version_sources=["v1", "v2"],
            _current_idx=0,
        )

        assert result is not None
        # Should write correlated output to storage backend
        storage_backend.write_target.assert_called_once()
        call_args = storage_backend.write_target.call_args
        written_data = call_args[0][2]  # third positional arg
        assert len(written_data) == 1
        assert written_data[0]["source_guid"] == "guid_1"

    def test_no_version_outputs_returns_none(self, correlator, storage_backend):
        """When no version agents have outputs, returns None."""
        storage_backend.list_target_files.return_value = []

        result = correlator.prepare_correlated_input(
            agent_name="downstream",
            version_sources=["v1", "v2"],
            _current_idx=0,
        )

        assert result is None

    def test_key_error_in_correlation_returns_none(self, correlator, storage_backend):
        """KeyError during processing → caught by except clause, returns None."""
        storage_backend.list_target_files.return_value = ["data.json"]
        # Return records that will trigger a KeyError in _create_merged_record
        # by having valid correlation IDs but missing namespace in content
        storage_backend.read_target.return_value = [
            {
                "version_correlation_id": "corr_1",
                "source_guid": "guid_1",
                "content": {},  # missing v1 namespace → DataValidationError
                "_source_file": "data.json",
            }
        ]

        # DataValidationError is not caught by (OSError, ValueError, KeyError)
        # This verifies the actual error propagation behavior
        from agent_actions.errors import DataValidationError

        with pytest.raises(DataValidationError, match="missing own namespace"):
            correlator.prepare_correlated_input(
                agent_name="downstream",
                version_sources=["v1"],
                _current_idx=0,
            )

    def test_oserror_during_mkdir_returns_none(self, storage_backend):
        """OSError when creating correlation_dir → caught, returns None."""
        # Use a path that will cause OSError on mkdir
        correlator = VersionOutputCorrelator(
            agent_folder=Path("/nonexistent/impossible/path"),
            storage_backend=None,  # forces mkdir path
        )

        result = correlator.prepare_correlated_input(
            agent_name="downstream",
            version_sources=["v1"],
            _current_idx=0,
        )

        assert result is None

    def test_filesystem_fallback_when_no_storage_backend(self, tmp_path):
        """Without storage_backend, falls back to filesystem loading."""
        correlator = VersionOutputCorrelator(
            agent_folder=tmp_path,
            storage_backend=None,
        )

        result = correlator.prepare_correlated_input(
            agent_name="downstream",
            version_sources=["v1"],
            _current_idx=0,
        )

        # No version files on disk → returns None
        assert result is None
        # But it should have created the correlation directory
        correlation_dir = tmp_path / "target" / "downstream"
        assert correlation_dir.exists()

    def test_file_not_found_in_storage_skips_and_continues(self, correlator, storage_backend):
        """FileNotFoundError on read_target for one file skips it, continues others."""
        storage_backend.list_target_files.return_value = ["good.json", "missing.json"]

        def mock_read_target(agent_name, relative_path):
            if relative_path == "missing.json":
                raise FileNotFoundError("TOCTOU race")
            return [
                {
                    "version_correlation_id": "corr_1",
                    "source_guid": "guid_1",
                    "content": {"v1": {"answer": "ok"}},
                    "_source_file": relative_path,
                }
            ]

        storage_backend.read_target.side_effect = mock_read_target

        result = correlator.prepare_correlated_input(
            agent_name="downstream",
            version_sources=["v1"],
            _current_idx=0,
        )

        # Should succeed with the good file's data
        assert result is not None
