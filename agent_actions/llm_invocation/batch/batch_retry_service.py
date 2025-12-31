"""Batch retry service for handling batch job retries.

This service encapsulates all retry-related functionality, extracted from
BatchService to follow Single Responsibility Principle.
"""

import logging
from typing import Optional, Dict, Any, List, Callable

from agent_actions.llm_invocation.batch.batch_constants import BatchStatus
from agent_actions.llm_invocation.batch.batch_context_manager import BatchContextManager
from agent_actions.llm_invocation.batch.batch_client_resolver import BatchClientResolver
from agent_actions.llm_invocation.batch.batch_registry_manager import BatchRegistryManager
from agent_actions.llm_invocation.batch.batch_retry_orchestrator import BatchRetryOrchestrator
from agent_actions.llm_invocation.batch.batch_retry_config import RetryConfig, get_retry_config
from agent_actions.llm_invocation.batch.batch_task_preparator import BatchTaskPreparator
from agent_actions.llm_invocation.providers.batch_client_base import BaseBatchClient, BatchResult
from agent_actions.errors import ProcessingError

logger = logging.getLogger(__name__)


class BatchRetryService:  # pylint: disable=too-few-public-methods
    """Service for handling batch job retry operations.

    Encapsulates retry orchestration, reconciliation, and retry chain management.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(
        self,
        client_resolver: BatchClientResolver,
        context_manager: BatchContextManager,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
        default_retry_config: Optional[RetryConfig] = None,
        task_preparator: Optional[BatchTaskPreparator] = None,
    ):
        """Initialize retry service with dependencies.

        Args:
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            registry_manager_factory: Factory function to create registry managers
            default_retry_config: Default retry configuration
            task_preparator: Task preparator for retry batches
        """
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._registry_manager_factory = registry_manager_factory
        self._default_retry_config = default_retry_config or RetryConfig.default()
        self._task_preparator = task_preparator
        self._retry_orchestrator: Optional[BatchRetryOrchestrator] = None

    # pylint: disable=too-many-locals
    def retry_batch_job(
        self,
        batch_id: str,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]] = None,
        max_attempts: Optional[int] = None,
    ) -> Optional[str]:
        """Manually retry a batch job.

        Triggers the retry orchestration for a completed batch that has missing records.

        Args:
            batch_id: ID of the batch to retry
            output_directory: Output directory containing batch registry
            agent_config: Agent configuration (loaded from registry if not provided)
            max_attempts: Override max retry attempts

        Returns:
            Retry batch ID if retry was triggered, None otherwise

        Raises:
            ProcessingError: If batch not found or not completed
        """
        manager = self._registry_manager_factory(output_directory)
        entry = manager.get_batch_job_by_id(batch_id)

        if not entry:
            raise ProcessingError(
                f"Batch job {batch_id} not found in registry",
                context={"batch_id": batch_id, "output_directory": output_directory},
            )

        if entry.status != BatchStatus.COMPLETED:
            raise ProcessingError(
                f"Batch job {batch_id} is not completed (status: {entry.status})",
                context={"batch_id": batch_id, "status": str(entry.status)},
            )

        # Find file_name for this batch
        file_name = self._find_file_name_for_batch(manager, batch_id)

        # Load context map
        context_map = self._context_manager.load_batch_context_map(output_directory, file_name)

        # Get provider
        provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

        # Retrieve results and reconcile
        batch_results = self._retrieve_results(
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=entry.record_count,
            file_name=file_name,
        )

        # Create reconciler to find missing records
        # pylint: disable=import-outside-toplevel
        from agent_actions.llm_invocation.batch.batch_result_reconciler import (
            BatchResultReconciler,
        )

        reconciler = BatchResultReconciler(context_map)
        for result in batch_results:
            reconciler.mark_processed(result.custom_id)
        reconciliation = reconciler.reconcile()

        if not reconciliation.missing_ids:
            logger.info("No missing records in batch %s, retry not needed", batch_id)
            return None

        # Build retry config
        retry_config = get_retry_config(agent_config, self._default_retry_config)
        if max_attempts is not None:
            retry_config = RetryConfig(enabled=True, max_attempts=max_attempts)

        # Get orchestrator and run retry chain
        orchestrator = self._get_retry_orchestrator(output_directory, manager)

        result = orchestrator.orchestrate_retry_chain(
            original_batch_id=batch_id,
            initial_reconciliation=reconciliation,
            context_map=context_map,
            agent_config=agent_config or {},
            output_directory=output_directory,
            original_file_name=file_name,
            retry_config=retry_config,
        )

        logger.info(
            "Retry chain completed for %s: %d attempts, %d success, %d still missing",
            batch_id,
            result.total_attempts,
            result.final_success_count,
            result.final_missing_count,
        )

        return result.retry_batch_ids[-1] if result.retry_batch_ids else None

    def _find_file_name_for_batch(self, manager: BatchRegistryManager, batch_id: str) -> str:
        """Find the file name associated with a batch ID.

        Args:
            manager: Registry manager to search
            batch_id: Batch ID to find

        Returns:
            File name if found, 'default' otherwise
        """
        for fname, entry in manager.get_all_jobs().items():
            if entry.batch_id == batch_id:
                return fname
        return "default"

    def _get_retry_orchestrator(
        self, _output_directory: str, manager: BatchRegistryManager
    ) -> BatchRetryOrchestrator:
        """Get or create retry orchestrator for output directory.

        Args:
            _output_directory: Output directory path (unused, kept for interface)
            manager: Registry manager instance

        Returns:
            BatchRetryOrchestrator instance
        """
        if self._retry_orchestrator is None:
            self._retry_orchestrator = BatchRetryOrchestrator(
                registry_manager=manager,
                client_resolver=self._client_resolver,
                task_preparator=self._task_preparator,
                context_manager=self._context_manager,
                retry_config=self._default_retry_config,
            )
        return self._retry_orchestrator

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _retrieve_results(
        self,
        provider: BaseBatchClient,
        batch_id: str,
        output_directory: Optional[str],
        *,
        context_map: Optional[Dict[str, Any]] = None,
        record_count: Optional[int] = None,
        file_name: Optional[str] = None,
    ) -> List[BatchResult]:
        """Retrieve batch results from provider and log reconciliation.

        Args:
            provider: Batch API client
            batch_id: Batch job ID
            output_directory: Output directory path
            context_map: Context map for reconciliation
            record_count: Expected record count
            file_name: Original file name

        Returns:
            List of batch results
        """
        # pylint: disable=import-outside-toplevel
        from agent_actions.llm_invocation.batch.batch_result_reconciler import (
            BatchResultReconciler,
        )

        batch_results = provider.retrieve_results(batch_id, output_directory)

        # Log reconciliation
        expected = BatchResultReconciler.collect_expected_custom_ids(context_map or {})
        received = BatchResultReconciler.collect_result_custom_ids(batch_results)
        BatchResultReconciler.log_batch_reconciliation(
            batch_id=batch_id,
            expected_count=len(expected) or record_count or 0,
            received_count=len(received),
            file_name=file_name,
        )

        return batch_results
