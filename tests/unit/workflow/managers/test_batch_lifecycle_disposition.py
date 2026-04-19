"""Tests for BatchLifecycleManager disposition-based passthrough paths.

Verifies that the manager routes passthrough checks through
has_disposition on the storage backend (always required).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError
from agent_actions.workflow.managers.batch import BatchLifecycleManager


@pytest.fixture
def mock_storage_backend():
    """Create a mock storage backend with disposition methods."""
    backend = MagicMock()
    backend.has_disposition.return_value = False
    return backend


@pytest.fixture
def mock_job_manager():
    """Create a mock job manager."""
    return MagicMock()


@pytest.fixture
def mock_processing_service():
    """Create a mock processing service."""
    return MagicMock()


class TestHandleBatchAgentPassthrough:
    """Test handle_batch_agent routes passthrough through DB when backend is set."""

    def test_no_batches_checks_db_disposition(
        self, mock_job_manager, mock_processing_service, mock_storage_backend
    ):
        """When registry says no_batches, checks DB for passthrough disposition."""
        mock_job_manager.get_registry_status.return_value = "no_batches"
        mock_storage_backend.has_disposition.return_value = True

        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )
        output_folder, status = manager.handle_batch_agent("extract", "/output/extract")

        mock_storage_backend.has_disposition.assert_called_once_with("extract", "passthrough")
        assert status == "completed"
        assert output_folder == "/output/extract"

    def test_no_batches_no_disposition_returns_failed(
        self, mock_job_manager, mock_processing_service, mock_storage_backend
    ):
        """When registry says no_batches and no DB disposition, returns failed."""
        mock_job_manager.get_registry_status.return_value = "no_batches"
        mock_storage_backend.has_disposition.return_value = False

        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )
        output_folder, status = manager.handle_batch_agent("extract", "/output/extract")

        assert status == "failed"
        assert output_folder is None

    def test_no_batches_fails_without_backend(self, mock_job_manager, mock_processing_service):
        """Without storage_backend, construction raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="requires a storage_backend"):
            BatchLifecycleManager(mock_job_manager, mock_processing_service)


class TestCheckBatchSubmission:
    """Test check_batch_submission routes passthrough through DB when backend is set."""

    def test_passthrough_via_db(
        self, mock_job_manager, mock_processing_service, mock_storage_backend
    ):
        """Returns 'passthrough' when DB has passthrough disposition."""
        mock_storage_backend.has_disposition.return_value = True

        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )
        # Create a tmp dir that exists but has no registry file
        agent_io = Path("/tmp/fake_agent_io")

        with patch.object(Path, "exists", return_value=False):
            result = manager.check_batch_submission("extract", 0, agent_io)

        mock_storage_backend.has_disposition.assert_called_once_with("extract", "passthrough")
        assert result == "passthrough"

    def test_no_passthrough_falls_through(
        self, mock_job_manager, mock_processing_service, mock_storage_backend
    ):
        """When DB has no passthrough, falls through to check output dir."""
        mock_storage_backend.has_disposition.return_value = False

        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )
        agent_io = Path("/tmp/fake_agent_io")

        with patch.object(Path, "exists", return_value=False):
            result = manager.check_batch_submission("extract", 0, agent_io)

        assert result is None


class TestCheckBatchSubmissionRunMode:
    """Test that configured_run_mode overrides stale batch file detection."""

    def test_online_mode_ignores_stale_registry(
        self, mock_job_manager, mock_processing_service, mock_storage_backend
    ):
        """Stale .batch_registry.json + run_mode=ONLINE → returns None."""
        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )
        agent_io = Path("/tmp/fake_agent_io")

        # Even with registry file present, ONLINE mode should return None
        with patch.object(Path, "exists", return_value=True):
            result = manager.check_batch_submission(
                "extract", 0, agent_io, configured_run_mode=RunMode.ONLINE
            )

        assert result is None

    def test_batch_mode_respects_registry(
        self, mock_job_manager, mock_processing_service, mock_storage_backend
    ):
        """Stale .batch_registry.json + run_mode=BATCH → returns 'batch_submitted'."""
        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )
        agent_io = Path("/tmp/fake_agent_io")

        with patch.object(Path, "exists", return_value=True):
            result = manager.check_batch_submission(
                "extract", 0, agent_io, configured_run_mode=RunMode.BATCH
            )

        assert result == "batch_submitted"

    def test_no_registry_online_mode(
        self, mock_job_manager, mock_processing_service, mock_storage_backend
    ):
        """No registry file + run_mode=ONLINE → returns None (short-circuits)."""
        mock_storage_backend.has_disposition.return_value = False

        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )
        agent_io = Path("/tmp/fake_agent_io")

        with patch.object(Path, "exists", return_value=False):
            result = manager.check_batch_submission(
                "extract", 0, agent_io, configured_run_mode=RunMode.ONLINE
            )

        assert result is None
        # Should not even check filesystem or dispositions
        mock_storage_backend.has_disposition.assert_not_called()

    def test_none_run_mode_preserves_existing_behavior(
        self, mock_job_manager, mock_processing_service, mock_storage_backend
    ):
        """configured_run_mode=None (default) → existing behavior unchanged."""
        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )
        agent_io = Path("/tmp/fake_agent_io")

        with patch.object(Path, "exists", return_value=True):
            result = manager.check_batch_submission("extract", 0, agent_io)

        assert result == "batch_submitted"
