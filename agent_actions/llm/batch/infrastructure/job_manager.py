"""Batch job lifecycle and registry status management."""

import json
import logging
from pathlib import Path

from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

logger = logging.getLogger(__name__)


class BatchJobManager:
    """Manages batch job lifecycle and registry status."""

    def __init__(
        self,
        client_resolver: BatchClientResolver,
        registry_manager: BatchRegistryManager | None = None,
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

    def _get_registry_manager(self, output_directory: str) -> BatchRegistryManager | None:
        if self._registry_manager is not None:
            return self._registry_manager

        registry_path = Path(output_directory) / "batch" / ".batch_registry.json"
        if not registry_path.exists():
            return None

        return BatchRegistryManager(registry_path)

    def are_all_jobs_completed(self, output_directory: str) -> bool:
        """Check if all batch jobs in the registry are completed.

        Args:
            output_directory: Directory containing the batch registry

        Returns:
            True if all jobs are completed, False otherwise
        """
        if not output_directory:
            return True

        registry_path = Path(output_directory) / "batch" / ".batch_registry.json"
        if not registry_path.exists():
            return True

        try:
            with open(registry_path, encoding="utf-8") as f:
                json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Registry file is malformed: %s", registry_path, exc_info=True)
            return False

        manager = self._get_registry_manager(output_directory)
        if manager is None:
            return True

        def check_provider(batch_id: str) -> str:
            return self._check_status(batch_id, output_directory)

        return manager.are_all_jobs_completed(check_provider=check_provider)

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

        manager = self._get_registry_manager(output_directory)
        if manager is None:
            return "no_batches"

        return manager.get_overall_status()
