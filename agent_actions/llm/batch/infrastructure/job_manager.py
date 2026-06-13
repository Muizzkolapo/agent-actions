"""Batch job lifecycle and registry status management."""

import logging
from typing import TYPE_CHECKING

from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class BatchJobManager:
    """Manages batch job lifecycle and registry status."""

    def __init__(
        self,
        client_resolver: BatchClientResolver,
        registry_manager: BatchRegistryManager | None = None,
        storage_backend: "StorageBackend | None" = None,
    ):
        """Initialize batch job manager.

        Args:
            client_resolver: Resolver for getting batch clients
            registry_manager: Optional registry manager (can be set later)
            storage_backend: Storage backend for registry persistence
        """
        self._client_resolver = client_resolver
        self._registry_manager = registry_manager
        self._storage_backend = storage_backend

    def set_registry_manager(self, registry_manager: BatchRegistryManager) -> None:
        """Set the registry manager (for lazy initialization)."""
        self._registry_manager = registry_manager

    def _check_status(
        self,
        batch_id: str,
        output_directory: str,
        agent_config: dict | None = None,
        registry_manager: BatchRegistryManager | None = None,
    ) -> str:
        """Check status of a batch job via client."""
        manager = registry_manager or self._registry_manager
        client = self._client_resolver.get_for_batch_id(
            batch_id, manager, output_directory, agent_config=agent_config
        )
        return client.check_status(batch_id)

    def _get_registry_manager(self, action_name: str) -> BatchRegistryManager | None:
        if self._registry_manager is not None:
            return self._registry_manager

        if self._storage_backend is None:
            return None

        return BatchRegistryManager(self._storage_backend, action_name)

    def are_all_jobs_completed(
        self, output_directory: str, agent_config: dict | None = None
    ) -> bool:
        """Check if all batch jobs in the registry are completed.

        Args:
            output_directory: Directory containing the batch registry (used as action_name)
            agent_config: Optional agent config for API key resolution

        Returns:
            True if all jobs are completed, False otherwise
        """
        if not output_directory:
            return True

        # Extract action_name from output_directory path
        from pathlib import Path

        action_name = Path(output_directory).name

        manager = self._get_registry_manager(action_name)
        if manager is None:
            return True

        if not manager.has_jobs():
            return True

        def check_provider(batch_id: str) -> str:
            return self._check_status(
                batch_id, output_directory, agent_config, registry_manager=manager
            )

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

        from pathlib import Path

        action_name = Path(output_directory).name

        manager = self._get_registry_manager(action_name)
        if manager is None:
            return "no_batches"

        if not manager.has_jobs():
            return "no_batches"

        return manager.get_overall_status()
