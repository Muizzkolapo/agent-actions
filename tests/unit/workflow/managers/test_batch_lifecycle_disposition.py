"""Tests for BatchLifecycleManager disposition-based passthrough paths.

Verifies that the manager routes passthrough checks through
has_disposition on the storage backend (always required).
"""

import json
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
    backend.load_metadata.return_value = None
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

    @pytest.mark.parametrize(
        ("has_disposition", "expected_folder", "expected_status"),
        [
            pytest.param(True, "/output/extract", "completed", id="passthrough-completes"),
            pytest.param(False, None, "failed", id="no-disposition-fails"),
        ],
    )
    def test_no_batches_reads_the_passthrough_disposition_from_the_db(
        self,
        mock_job_manager,
        mock_processing_service,
        mock_storage_backend,
        has_disposition,
        expected_folder,
        expected_status,
    ):
        mock_job_manager.get_registry_status.return_value = "no_batches"
        mock_storage_backend.has_disposition.return_value = has_disposition

        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )
        output_folder, status = manager.handle_batch_agent("extract", "/output/extract")

        mock_storage_backend.has_disposition.assert_called_once_with("extract", "passthrough")
        assert status == expected_status
        assert output_folder == expected_folder

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

    def test_a_collected_batch_is_not_reported_as_a_submission(
        self, mock_job_manager, mock_processing_service, mock_storage_backend
    ):
        """An entry stamped collected is spent. Reporting it as a submission pauses
        the run to collect a batch with nothing left to give, and the action never
        reaches its completion handling. The stamp is what says so — see the test
        below for why the COMPLETED status cannot."""
        mock_storage_backend.load_metadata.return_value = json.dumps(
            {
                "pages.json": {
                    "batch_id": "b_spent",
                    "status": "completed",
                    "timestamp": "t",
                    "provider": "p",
                    "collected_at": "2026-01-01T00:00:00Z",
                }
            }
        )
        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )

        with patch.object(Path, "exists", return_value=False):
            result = manager.check_batch_submission("extract", 0, Path("/tmp/fake_agent_io"))

        assert result is None

    _SPENT = {
        "batch_id": "b_spent",
        "status": "completed",
        "timestamp": "t",
        "provider": "p",
        "collected_at": "2026-01-01T00:00:00Z",
    }

    @pytest.mark.parametrize(
        "registry",
        [
            # COMPLETED does not mean collected: the status a provider poll returned is
            # persisted before any result is retrieved. Treating it as spent completes
            # the action with none of its records and strands the batch.
            pytest.param(
                {
                    "pages.json": {
                        "batch_id": "b_ready",
                        "status": "completed",
                        "timestamp": "t",
                        "provider": "p",
                    }
                },
                id="completed-but-never-collected",
            ),
            # The spent entry must not mask the live one. Kept apart from the case above
            # so a fix that simply stops reading the registry cannot hold both.
            pytest.param(
                {
                    "done.json": _SPENT,
                    "live.json": {
                        "batch_id": "b_live",
                        "status": "submitted",
                        "timestamp": "t",
                        "provider": "p",
                    },
                },
                id="uncollected-beside-spent",
            ),
            # A FAILED entry has delivered nothing and is resubmitted, so it is not
            # spent. Pinned so narrowing the check to in-flight statuses cannot pass.
            pytest.param(
                {
                    "f.json": {
                        "batch_id": "b_failed",
                        "status": "failed",
                        "timestamp": "t",
                        "provider": "p",
                    }
                },
                id="failed",
            ),
        ],
    )
    def test_a_batch_not_yet_collected_still_pauses(
        self, mock_job_manager, mock_processing_service, mock_storage_backend, registry
    ):
        mock_storage_backend.load_metadata.return_value = json.dumps(registry)
        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )

        result = manager.check_batch_submission("extract", 0, Path("/tmp/fake_agent_io"))

        assert result == "batch_submitted"


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

        with patch.object(Path, "exists", return_value=True):
            result = manager.check_batch_submission(
                "extract", 0, agent_io, configured_run_mode=RunMode.ONLINE
            )

        assert result is None

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

    @pytest.mark.parametrize(
        "run_mode",
        [pytest.param(RunMode.BATCH, id="batch-mode"), pytest.param(None, id="run-mode-unset")],
    )
    def test_a_pending_batch_in_the_backend_is_reported_as_submitted(
        self, mock_job_manager, mock_processing_service, mock_storage_backend, run_mode
    ):
        mock_storage_backend.load_metadata.return_value = json.dumps(
            {
                "file.json": {
                    "batch_id": "b1",
                    "status": "pending",
                    "timestamp": "t",
                    "provider": "p",
                }
            }
        )
        manager = BatchLifecycleManager(
            mock_job_manager, mock_processing_service, storage_backend=mock_storage_backend
        )

        result = manager.check_batch_submission(
            "extract", 0, Path("/tmp/fake_agent_io"), configured_run_mode=run_mode
        )

        assert result == "batch_submitted"
