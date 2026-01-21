"""Batch job lifecycle and registry status management."""

import json
import logging
from pathlib import Path
from typing import Optional

from agent_actions.llm_invocation.batch.infrastructure.batch_registry_manager import (
    BatchRegistryManager,
)
from agent_actions.llm_invocation.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus

logger = logging.getLogger(__name__)


class BatchJobManager:
    """
    Manages batch job lifecycle and registry status.

    Handles checking job completion status and aggregating registry state.
    """

    def __init__(
        self,
        client_resolver: BatchClientResolver,
        registry_manager: Optional[BatchRegistryManager] = None,
    ):
        """Initialize batch job manager.

        Args:
            client_resolver: Resolver for getting batch clients
            registry_manager: Optional registry manager (can be set later)
        """
        self._client_resolver = client_resolver
        self._registry_manager = registry_manager

    def set_registry_manager(self, registry_manager: BatchRegistryManager) -> None:
        """Set the registry manager (for lazy initialization)."""
        self._registry_manager = registry_manager

    def _check_status(self, batch_id: str, output_directory: str) -> str:
        """Check status of a batch job via client."""
        manager = self._registry_manager
        client = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)
        return client.check_status(batch_id)

    def are_all_jobs_completed(self, output_directory: str) -> bool:
        """Check if all batch jobs in the registry are completed.

        Args:
            output_directory: Directory containing the batch registry

        Returns:
            True if all jobs are completed, False otherwise
        """
        if not output_directory:
            return True

        registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
        if not registry_file.exists():
            return True

        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                registry = json.load(f)

            if not registry:
                return True

            for file_name, entry in registry.items():
                batch_id = entry.get("batch_id")
                if not batch_id:
                    continue

                try:
                    actual_status = self._check_status(batch_id, str(output_directory))
                    if actual_status != entry.get("status"):
                        entry["status"] = actual_status

                    if actual_status not in BatchStatus.terminal_states():
                        return False

                except Exception as e:
                    logger.warning(
                        "Failed to check status for batch %s in registry: %s",
                        batch_id,
                        e,
                        exc_info=True,
                        extra={
                            "batch_id": batch_id,
                            "file_name": file_name,
                            "output_directory": output_directory,
                            "operation": "registry_status_check",
                        },
                    )
                    return False

            # Update registry file with new statuses
            with open(registry_file, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=2)

            return True

        except (json.JSONDecodeError, KeyError):
            return True

    def get_registry_status(self, output_directory: str) -> str:
        """Get the overall status of all batch jobs in the registry.

        Args:
            output_directory: Directory containing the batch registry

        Returns:
            Status string: 'completed', 'in_progress', 'partial_failed',
                          'no_batches', 'error', or 'unknown'
        """
        if not output_directory:
            return "no_batches"

        registry_file = Path(output_directory) / "batch" / ".batch_registry.json"
        if not registry_file.exists():
            return "no_batches"

        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                registry = json.load(f)

            if not registry:
                return "no_batches"

            completed_count = 0
            failed_count = 0
            in_progress_count = 0

            for file_name, entry in registry.items():
                batch_id = entry.get("batch_id")
                if not batch_id:
                    continue

                try:
                    actual_status = self._check_status(batch_id, str(output_directory))
                    if actual_status == BatchStatus.COMPLETED:
                        completed_count += 1
                    elif actual_status in (BatchStatus.FAILED, BatchStatus.CANCELLED):
                        failed_count += 1
                    else:
                        in_progress_count += 1

                except Exception as e:
                    logger.debug(
                        "Could not check status for batch %s, treating as in_progress: %s",
                        batch_id,
                        e,
                        extra={
                            "batch_id": batch_id,
                            "file_name": file_name,
                            "operation": "status_aggregation",
                        },
                    )
                    in_progress_count += 1

            total_jobs = len(registry)
            if completed_count == total_jobs:
                return "completed"
            if failed_count > 0:
                return "partial_failed"
            if in_progress_count > 0:
                return "in_progress"
            return "unknown"

        except (json.JSONDecodeError, KeyError):
            return "error"
