"""Batch submission service for submitting batch jobs.

This service encapsulates all batch submission functionality, extracted from
BatchService to follow Single Responsibility Principle.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List, Callable, Union

from agent_actions.logging.context import CorrelationContext
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.batch_context_manager import (
    BatchContextManager,
)
from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.batch_registry_manager import (
    BatchRegistryManager,
)
from agent_actions.llm.batch.processing.batch_task_preparator import BatchTaskPreparator
from agent_actions.llm.batch.processing.batch_passthrough_builder import (
    BatchPassthroughBuilder,
)
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.errors import ConfigValidationError, ExternalServiceError

logger = logging.getLogger(__name__)


class BatchSubmissionService:
    """Service for submitting batch jobs.

    Handles task preparation, batch submission to providers, and registry management.
    """

    def __init__(
        self,
        task_preparator: BatchTaskPreparator,
        client_resolver: BatchClientResolver,
        context_manager: BatchContextManager,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
        force_batch: bool = False,
    ):
        """Initialize submission service with dependencies.

        Args:
            task_preparator: Preparator for batch tasks
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            registry_manager_factory: Factory function to create registry managers
            force_batch: Whether to force new batch submission
        """
        self._task_preparator = task_preparator
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._registry_manager_factory = registry_manager_factory
        self._force_batch = force_batch

    def prepare_batch_tasks(
        self,
        agent_config: Dict[str, Any],
        data: List[Dict[str, Any]],
        output_directory: Optional[str] = None,
        batch_name: Optional[str] = None,
        source_data: Optional[Any] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Prepare batch tasks from data.

        Args:
            agent_config: Agent configuration
            data: Input data to process
            output_directory: Output directory path
            batch_name: Name for the batch

        Returns:
            Tuple of (tasks, context_map)
        """
        provider = self._client_resolver.get_for_config(agent_config)
        prepared = self._task_preparator.prepare_tasks(
            agent_config=agent_config,
            data=data,
            provider=provider,
            output_directory=output_directory,
            batch_name=batch_name,
            source_data=source_data,
        )
        logger.debug(
            "Task preparation complete: %d tasks, %d filtered, %d skipped",
            prepared.task_count,
            prepared.stats.filtered_items,
            prepared.stats.skipped_items,
        )
        return prepared.tasks, prepared.context_map

    def check_status(self, batch_id: str, output_directory: Optional[str] = None) -> BatchStatus:
        """Check the status of a batch job.

        Args:
            batch_id: ID of the batch job
            output_directory: Output directory for registry lookup

        Returns:
            Current batch status

        Raises:
            ExternalServiceError: If status check fails
        """
        provider = None
        try:
            manager = self._registry_manager_factory(output_directory) if output_directory else None
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)
            return provider.check_status(batch_id)
        except Exception as e:
            vendor = (
                getattr(provider, "vendor_type", "unknown") if provider is not None else "unknown"
            )
            raise ExternalServiceError(vendor, f"Failed to check batch status: {e}", cause=e) from e

    def submit_batch_job(
        self,
        agent_config: Dict[str, Any],
        batch_name: str,
        data: List[Dict[str, Any]],
        output_directory: Optional[str] = None,
        force: bool = False,
        source_data: Optional[Any] = None,
    ) -> Union[str, Dict[str, Any]]:
        """Submit a batch job for processing.

        Args:
            agent_config: Agent configuration
            batch_name: Name for the batch
            data: Input data to process
            output_directory: Output directory path
            force: Force new submission even if in-flight batch exists

        Returns:
            Batch ID if submitted, or passthrough dict if no tasks

        Raises:
            ConfigValidationError: If model_vendor missing
            ExternalServiceError: If submission fails
        """
        force_submission = force or self._force_batch

        # Check for existing in-flight batch
        if not force_submission and output_directory:
            manager = self._registry_manager_factory(output_directory)
            entry = manager.get_batch_job(batch_name or "default")
            if entry and entry.is_in_flight:
                logger.info(
                    "Found existing in-flight batch job for %s: %s",
                    batch_name,
                    entry.batch_id,
                )
                logger.info(
                    "Skipping new batch submission. "
                    "Use --batch_continue to process completed batches."
                )
                return entry.batch_id

        # Prepare tasks
        tasks, context_map = self.prepare_batch_tasks(
            agent_config, data, output_directory, batch_name, source_data
        )

        # Handle empty tasks
        if not tasks:
            return self._handle_empty_tasks(agent_config, context_map, data, output_directory)

        # Save context map
        self._context_manager.save_batch_context_map(context_map, output_directory, batch_name)

        # Submit to provider
        return self._submit_to_provider(agent_config, batch_name, tasks, output_directory)

    def _handle_empty_tasks(
        self,
        agent_config: Dict[str, Any],
        context_map: Dict[str, Any],
        data: List[Dict[str, Any]],
        output_directory: Optional[str],
    ) -> Dict[str, Any]:
        """Handle case where no tasks remain after filtering.

        Args:
            agent_config: Agent configuration
            context_map: Context map from preparation
            data: Original input data
            output_directory: Output directory path

        Returns:
            Passthrough dict
        """
        where_config = agent_config.get("where_clause") or {}
        behavior = where_config.get("behavior", "filter")

        if behavior == "filter":
            return {"type": "passthrough", "data": [], "output_directory": output_directory}
        if behavior == "skip":
            return BatchPassthroughBuilder(output_directory).from_context(
                context_map, reason="where_clause_not_matched"
            )
        return BatchPassthroughBuilder(output_directory).from_data(
            data, reason="conditional_clause_failed"
        )

    def _submit_to_provider(
        self,
        agent_config: Dict[str, Any],
        batch_name: str,
        tasks: List[Dict[str, Any]],
        output_directory: Optional[str],
    ) -> str:
        """Submit batch to provider and save to registry.

        Args:
            agent_config: Agent configuration
            batch_name: Batch name
            tasks: Prepared tasks
            output_directory: Output directory path

        Returns:
            Batch ID

        Raises:
            ConfigValidationError: If model_vendor missing
            ExternalServiceError: If submission fails
        """
        provider_type = agent_config.get("model_vendor")
        if not provider_type:
            raise ConfigValidationError(
                "model_vendor",
                "Missing required field 'model_vendor' for batch processing.",
            )
        provider_type = provider_type.lower()

        try:
            provider = self._client_resolver.get_for_config(agent_config)
            batch_id, initial_status = provider.submit_batch(tasks, batch_name, output_directory)

            # Set batch_id in correlation context
            CorrelationContext.set_batch(batch_id)

            # Log submission
            logger.info(
                "Batch job submitted",
                extra={
                    "operation": "submit_batch_job",
                    "batch_id": batch_id,
                    "batch_name": batch_name,
                    "batch_size": len(tasks),
                    "provider": provider_type,
                    "initial_status": initial_status,
                },
            )

            # Save to registry
            if output_directory:
                manager = self._registry_manager_factory(output_directory)
                entry = BatchJobEntry(
                    batch_id=batch_id,
                    status=initial_status,
                    timestamp=datetime.now().isoformat(),
                    provider=provider_type,
                    record_count=len(tasks),
                    workflow_session_id=agent_config.get("workflow_session_id"),
                )
                manager.save_batch_job(batch_name or "default", entry)

            return batch_id

        except ConfigValidationError:
            raise
        except Exception as e:
            raise ExternalServiceError(
                provider_type, f"Failed to submit batch job: {e}", cause=e
            ) from e
