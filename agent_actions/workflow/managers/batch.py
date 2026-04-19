"""Batch job lifecycle management for status checking and result processing."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from rich.console import Console

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError, ProcessingError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    BatchErrorEvent,
    BatchPassthroughEvent,
    BatchProcessingCompleteEvent,
    BatchResultsProcessedEvent,
    BatchStatusEvent,
)
from agent_actions.storage.backend import DISPOSITION_DEFERRED, DISPOSITION_PASSTHROUGH

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class BatchLifecycleManager:
    """Manages batch job lifecycle and result processing."""

    def __init__(
        self,
        job_manager,
        processing_service,
        console: Console | None = None,
        storage_backend: Optional["StorageBackend"] = None,
    ):
        """Initialize batch lifecycle manager.

        Args:
            job_manager: BatchJobManager for registry status and completion checks.
            processing_service: BatchProcessingService for result processing.
            console: Optional Rich console for output.
            storage_backend: Required storage backend for disposition tracking.

        Raises:
            ConfigurationError: If storage_backend is None
        """
        if storage_backend is None:
            raise ConfigurationError(
                "BatchLifecycleManager requires a storage_backend. "
                "Disposition tracking is not optional.",
                context={"component": "BatchLifecycleManager"},
            )
        self.job_manager = job_manager
        self.processing_service = processing_service
        self.console = console or Console()
        self.storage_backend = storage_backend

    def handle_batch_agent(
        self, agent_name: str, output_directory: str, agent_config: dict[str, Any] | None = None
    ) -> tuple[str | None, str]:
        """Check batch status and process results.

        Returns:
            (output_folder or None, batch_status) where status is
            'completed', 'in_progress', or 'failed'.
        """
        registry_status = self.job_manager.get_registry_status(output_directory)

        if registry_status == "completed":
            fire_event(BatchProcessingCompleteEvent(action_name=agent_name))
            self._process_batch_results(output_directory, agent_config, agent_name)
            # Re-check — processing may have submitted recovery batches
            new_status = self.job_manager.get_registry_status(output_directory)
            if new_status != "completed":
                return (None, "in_progress")
            fire_event(BatchResultsProcessedEvent(action_name=agent_name))
            return (output_directory, "completed")

        if registry_status in ["in_progress", "partial_failed"]:
            if self.job_manager.are_all_jobs_completed(output_directory):
                fire_event(BatchProcessingCompleteEvent(action_name=agent_name))
                self._process_batch_results(output_directory, agent_config, agent_name)
                # Re-check — processing may have submitted recovery batches
                new_status = self.job_manager.get_registry_status(output_directory)
                if new_status != "completed":
                    return (None, "in_progress")
                fire_event(BatchResultsProcessedEvent(action_name=agent_name))
                return (output_directory, "completed")
            return (None, "in_progress")

        if registry_status == "no_batches":
            has_passthrough = self.storage_backend.has_disposition(
                agent_name, DISPOSITION_PASSTHROUGH
            )
            if has_passthrough:
                fire_event(BatchPassthroughEvent(action_name=agent_name))
                return (output_directory, "completed")
            fire_event(
                BatchStatusEvent(
                    action_name=agent_name,
                    status_message=f"No batch jobs found for {agent_name}",
                    status_type="warning",
                )
            )
            return (None, "failed")

        return (None, "failed")

    def _process_batch_results(
        self, output_directory: str, agent_config: dict[str, Any] | None, agent_name: str
    ):
        """Process all completed batch job results.

        Raises:
            ProcessingError: If result processing fails.
        """
        try:
            processed_files = self.processing_service.process_all_batch_results(
                output_directory, agent_config=agent_config, action_name=agent_name
            )
            if not processed_files:
                logger.info(
                    "No files processed for %s — recovery batches may be pending",
                    agent_name,
                )

        except ProcessingError:
            fire_event(
                BatchErrorEvent(
                    action_name=agent_name,
                    error_message="Could not process batch results",
                    error_type="ProcessingError",
                )
            )
            raise
        except Exception as e:
            fire_event(
                BatchErrorEvent(
                    action_name=agent_name,
                    error_message=f"Could not process batch results: {str(e)}",
                    error_type=type(e).__name__,
                )
            )
            raise

        self._warn_orphaned_deferred(agent_name)

    def _warn_orphaned_deferred(self, agent_name: str) -> None:
        """Log a warning if DEFERRED dispositions remain after batch processing.

        Orphaned DEFERRED records indicate records that were queued for batch
        execution but never received a final result — e.g. due to a submission
        failure or a provider-side drop.  This is diagnostic only and never
        raises.
        """
        try:
            orphans = self.storage_backend.get_disposition(
                agent_name, disposition=DISPOSITION_DEFERRED
            )
            if orphans:
                sample_ids = [r.get("record_id", "?") for r in orphans[:10]]
                logger.warning(
                    "[%s] %d record(s) still in DEFERRED state after batch completion "
                    "— possible orphans: %s",
                    agent_name,
                    len(orphans),
                    sample_ids,
                )
        except Exception:
            logger.debug(
                "Could not check for orphaned DEFERRED dispositions for %s",
                agent_name,
                exc_info=True,
            )

    def check_batch_submission(
        self,
        agent_name: str,
        agent_idx: int,
        agent_io_path: Path,
        configured_run_mode: RunMode | None = None,
    ) -> str | None:
        """Return 'batch_submitted', 'passthrough', 'no_batches', or None."""
        # YAML config is authoritative — stale batch files do not override
        if configured_run_mode == RunMode.ONLINE:
            return None

        node_output_dir = agent_io_path / "target" / agent_name
        registry_file = node_output_dir / "batch" / ".batch_registry.json"

        if registry_file.exists():
            return "batch_submitted"

        # Check passthrough disposition
        if self.storage_backend.has_disposition(agent_name, DISPOSITION_PASSTHROUGH):
            return "passthrough"

        if node_output_dir.exists():
            # Output dir exists but no batch registry or passthrough
            return "no_batches"
        return None
