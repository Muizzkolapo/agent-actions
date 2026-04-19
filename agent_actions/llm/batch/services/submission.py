"""Batch submission service for task preparation and job submission."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from agent_actions.errors import ConfigurationError, ConfigValidationError, ExternalServiceError
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry, SubmissionResult
from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
)
from agent_actions.llm.batch.infrastructure.registry import (
    BatchRegistryManager,
)
from agent_actions.llm.batch.processing.batch_passthrough_builder import (
    BatchPassthroughBuilder,
)
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.logging.core.manager import fire_event, get_manager
from agent_actions.logging.events import BatchSubmittedEvent
from agent_actions.logging.events.batch_events import (
    BatchStatusCheckFailedEvent,
    BatchSubmissionFailedEvent,
)

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
        agent_config: dict[str, Any],
        data: list[dict[str, Any]],
        output_directory: str | None = None,
        batch_name: str | None = None,
        source_data: Any | None = None,
        workflow_metadata: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Prepare batch tasks from data.

        Args:
            agent_config: Agent configuration
            data: Input data to process
            output_directory: Output directory path
            batch_name: Name for the batch
            workflow_metadata: Optional workflow metadata for {{ workflow.* }} templates

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
            workflow_metadata=workflow_metadata,
        )
        logger.debug(
            "Task preparation complete: %d tasks, %d filtered, %d skipped",
            prepared.task_count,
            prepared.stats.total_filtered,
            prepared.stats.total_skipped,
        )
        return prepared.tasks, prepared.context_map

    def check_status(self, batch_id: str, output_directory: str | None = None) -> BatchStatus:
        """Check the status of a batch job.

        Args:
            batch_id: ID of the batch job
            output_directory: Output directory for registry lookup

        Returns:
            Current batch status

        Raises:
            ConfigurationError: If output_directory is None
            ExternalServiceError: If status check fails
        """
        if output_directory is None:
            raise ConfigurationError(
                "check_status requires output_directory to resolve the batch provider",
                context={"batch_id": batch_id},
            )
        provider = None
        try:
            manager = self._registry_manager_factory(output_directory)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)
            return provider.check_status(batch_id)  # type: ignore[return-value]
        except ConfigurationError:
            raise
        except Exception as e:
            vendor = (
                getattr(provider, "vendor_type", "unknown") if provider is not None else "unknown"
            )
            fire_event(
                BatchStatusCheckFailedEvent(
                    batch_id=batch_id,
                    provider=vendor,
                    error=str(e),
                )
            )
            raise ExternalServiceError(
                f"Failed to check batch status: {e}", context={"vendor": vendor}, cause=e
            ) from e

    def submit_batch_job(
        self,
        agent_config: dict[str, Any],
        batch_name: str,
        data: list[dict[str, Any]],
        output_directory: str | None = None,
        force: bool = False,
        source_data: Any | None = None,
        workflow_metadata: dict[str, Any] | None = None,
    ) -> SubmissionResult:
        """Submit a batch job for processing.

        Args:
            agent_config: Agent configuration
            batch_name: Name for the batch
            data: Input data to process
            output_directory: Output directory path
            force: Force new submission even if in-flight batch exists
            workflow_metadata: Optional workflow metadata for {{ workflow.* }} templates

        Returns:
            SubmissionResult with batch_id if submitted, or passthrough dict if no tasks

        Raises:
            ConfigValidationError: If model_vendor missing
            ExternalServiceError: If submission fails
        """
        force_submission = force or self._force_batch

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
                return SubmissionResult(batch_id=entry.batch_id)
            # Only COMPLETED blocks resubmission. FAILED/CANCELLED fall through
            # so the framework can retry automatically without --force.
            if entry and entry.status == BatchStatus.COMPLETED:
                logger.info(
                    "Found completed batch job for %s: %s — skipping resubmission",
                    batch_name,
                    entry.batch_id,
                )
                return SubmissionResult(batch_id=entry.batch_id)

        tasks, context_map = self.prepare_batch_tasks(
            agent_config, data, output_directory, batch_name, source_data, workflow_metadata
        )

        if not tasks:
            return self._handle_empty_tasks(agent_config, context_map, data, output_directory)

        if output_directory:
            self._context_manager.save_batch_context_map(context_map, output_directory, batch_name)

        return self._submit_to_provider(agent_config, batch_name, tasks, output_directory)

    def _handle_empty_tasks(
        self,
        agent_config: dict[str, Any],
        context_map: dict[str, Any],
        data: list[dict[str, Any]],
        output_directory: str | None,
    ) -> SubmissionResult:
        """Handle case where no tasks remain after filtering.

        Args:
            agent_config: Agent configuration
            context_map: Context map from preparation
            data: Original input data
            output_directory: Output directory path

        Returns:
            SubmissionResult with passthrough dict
        """
        where_config = agent_config.get("where_clause") or {}
        behavior = where_config.get("behavior", "filter")

        if behavior == "filter":
            passthrough: dict[str, Any] = {
                "type": "tombstone",
                "data": [],
                "output_directory": output_directory,
            }
        elif behavior == "skip":
            passthrough = BatchPassthroughBuilder(output_directory).from_context(
                context_map, reason="where_clause_not_matched"
            )
        else:
            passthrough = BatchPassthroughBuilder(output_directory).from_data(
                data, reason="conditional_clause_failed"
            )
        return SubmissionResult(passthrough=passthrough)

    def _submit_to_provider(
        self,
        agent_config: dict[str, Any],
        batch_name: str,
        tasks: list[dict[str, Any]],
        output_directory: str | None,
    ) -> SubmissionResult:
        """Submit batch to provider and save to registry.

        Args:
            agent_config: Agent configuration
            batch_name: Batch name
            tasks: Prepared tasks
            output_directory: Output directory path

        Returns:
            SubmissionResult with batch_id

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
        batch_id = "unknown"  # Initialize for error handling

        try:
            provider = self._client_resolver.get_for_config(agent_config)
            batch_id, initial_status = provider.submit_batch(tasks, batch_name, output_directory)

            get_manager().set_context(batch_id=batch_id)

            fire_event(
                BatchSubmittedEvent(
                    batch_id=batch_id,
                    action_name=batch_name or "default",
                    request_count=len(tasks),
                    provider=provider_type,
                )
            )

            if output_directory:
                manager = self._registry_manager_factory(output_directory)
                file_key = batch_name or "default"
                entry = BatchJobEntry(
                    batch_id=batch_id,
                    status=initial_status,
                    timestamp=datetime.now(UTC).isoformat(),
                    provider=provider_type,
                    record_count=len(tasks),
                    workflow_session_id=agent_config.get("workflow_session_id"),
                    file_name=file_key,
                    is_versioned_agent=agent_config.get("is_versioned_agent"),
                    version_base_name=agent_config.get("version_base_name"),
                )
                manager.save_batch_job(file_key, entry)

            return SubmissionResult(batch_id=batch_id)

        except ConfigValidationError:
            raise
        except Exception as e:
            fire_event(
                BatchSubmissionFailedEvent(
                    batch_id=batch_id,
                    provider=provider_type,
                    error=str(e),
                )
            )
            raise ExternalServiceError(
                f"Failed to submit batch job: {e}", context={"vendor": provider_type}, cause=e
            ) from e
