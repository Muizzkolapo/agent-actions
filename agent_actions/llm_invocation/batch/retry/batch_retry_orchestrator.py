"""
Batch Retry Orchestrator.

Orchestrates automatic retry of failed/missing batch records.
Handles the full retry chain lifecycle from detection to result merging.
"""

# pylint: disable=duplicate-code

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from agent_actions.llm_invocation.batch.retry.batch_retry_config import (
    RetryConfig,
    get_retry_config,
)
from agent_actions.llm_invocation.batch.core.batch_models import BatchJobEntry
from agent_actions.llm_invocation.batch.processing.batch_result_reconciler import (
    BatchReconciliationResult,
)
from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus, ContextMetaKeys
from agent_actions.llm_invocation.batch.core.batch_context_metadata import BatchContextMetadata

logger = logging.getLogger(__name__)


@dataclass
class RetryMetadata:
    """
    Metadata about retry attempts for a single record.

    Attached to each output record to track retry history.
    """

    was_retried: bool = False
    retry_attempts: int = 0  # 0 = succeeded on original batch
    original_batch_id: Optional[str] = None
    final_batch_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "was_retried": self.was_retried,
            "retry_attempts": self.retry_attempts,
            "original_batch_id": self.original_batch_id,
            "final_batch_id": self.final_batch_id,
        }


@dataclass
class RetryBatchResult:
    """
    Result of a single retry batch submission and processing.

    Tracks what happened to each record in the retry batch.
    """

    batch_id: str
    retry_attempt: int
    submitted_count: int
    success_ids: Set[str] = field(default_factory=set)
    missing_ids: Set[str] = field(default_factory=set)
    processed_data: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        """Check if all records in this retry succeeded."""
        return len(self.missing_ids) == 0


@dataclass
class RetryChainResult:
    """
    Result of the complete retry chain orchestration.

    Contains merged results from all batches with retry metadata.
    """

    original_batch_id: str
    total_attempts: int  # 0 = original only, N = N retries performed
    final_success_count: int
    final_missing_count: int
    all_processed_data: List[Dict[str, Any]] = field(default_factory=list)
    retry_batch_ids: List[str] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        """Check if all records ultimately succeeded."""
        return self.final_missing_count == 0


class BatchRetryOrchestrator:
    """
    Orchestrates automatic retry of failed/missing batch records.

    Coordinates the full retry lifecycle:
    1. Detect missing records after batch completion
    2. Determine if retry should be triggered based on config
    3. Prepare and submit retry batches
    4. Track retry metadata per record
    5. Merge results from all batches

    Example:
        orchestrator = BatchRetryOrchestrator(
            registry_manager=registry_manager,
            client_resolver=client_resolver,
            task_preparator=task_preparator,
            context_manager=context_manager,
        )

        result = orchestrator.orchestrate_retry_chain(
            original_batch_id="batch_001",
            reconciliation=reconciliation,
            context_map=context_map,
            agent_config=agent_config,
            output_directory="/path/to/output",
        )
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals

    # Poll interval for checking batch status (seconds)
    DEFAULT_POLL_INTERVAL = 30
    MAX_POLL_ATTEMPTS = 1000  # Safety limit

    def __init__(
        self,
        registry_manager: Any,  # BatchRegistryManager
        client_resolver: Any,  # BatchClientResolver
        task_preparator: Any,  # BatchTaskPreparator
        context_manager: Any,  # BatchContextManager
        retry_config: Optional[RetryConfig] = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ):
        """
        Initialize retry orchestrator.

        Args:
            registry_manager: Manager for batch registry operations
            client_resolver: Resolver for getting batch clients by provider
            task_preparator: Preparator for creating batch tasks
            context_manager: Manager for batch context maps
            retry_config: Default retry configuration (can be overridden per call)
            poll_interval: Seconds between status polls
        """
        self._registry_manager = registry_manager
        self._client_resolver = client_resolver
        self._task_preparator = task_preparator
        self._context_manager = context_manager
        self._default_retry_config = retry_config or RetryConfig.default()
        self._poll_interval = poll_interval

    def should_retry(
        self,
        missing_ids: Set[str],
        current_attempt: int,
        retry_config: Optional[RetryConfig] = None,
    ) -> bool:
        """
        Determine if a retry should be triggered.

        Args:
            missing_ids: Set of custom_ids that are missing from results
            current_attempt: Current retry attempt (0 = original batch)
            retry_config: Retry configuration to use

        Returns:
            True if retry should be triggered
        """
        config = retry_config or self._default_retry_config

        # No missing records -> no retry needed
        if not missing_ids:
            logger.debug("No missing records, retry not needed")
            return False

        # Check if we've exhausted retry attempts
        if not config.should_retry(current_attempt):
            logger.info(
                "Max retry attempts (%d) reached, not retrying %d missing records",
                config.max_attempts,
                len(missing_ids),
            )
            return False

        logger.info(
            "Retry triggered: %d missing records, attempt %d of %d",
            len(missing_ids),
            current_attempt + 1,
            config.max_attempts,
        )
        return True

    def get_retry_records(
        self,
        missing_ids: Set[str],
        context_map: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Extract original record data for failed/missing records.

        Args:
            missing_ids: Set of custom_ids to retry
            context_map: Full context map with all original records

        Returns:
            Filtered context map containing only records to retry
        """
        retry_context = {}
        for custom_id in missing_ids:
            if custom_id in context_map:
                retry_context[custom_id] = context_map[custom_id].copy()
            else:
                logger.warning(
                    "Missing record %s not found in context map, skipping",
                    custom_id,
                )
        return retry_context

    def prepare_retry_tasks(
        self,
        retry_context: Dict[str, Any],
        agent_config: Dict[str, Any],
        provider: Any,  # BaseBatchClient
        output_directory: str,
        parent_batch_id: str,
        retry_attempt: int,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Prepare batch tasks for retry records.

        Args:
            retry_context: Context map for records to retry
            agent_config: Agent configuration
            provider: Batch client for the provider
            output_directory: Output directory path
            parent_batch_id: ID of parent batch being retried
            retry_attempt: Current retry attempt number

        Returns:
            Tuple of (tasks, updated_context_map)
        """
        # Generate retry batch name
        retry_batch_name = f"{parent_batch_id}_r{retry_attempt}"

        # Convert context map back to data list for task preparation
        # The context map values contain the original row data
        retry_data = []
        for record_data in retry_context.values():
            # Extract the original content, preserving all fields
            record_copy = record_data.copy()
            # Remove internal tracking fields that shouldn't affect task preparation
            record_copy.pop(ContextMetaKeys.FILTER_STATUS, None)
            record_copy.pop(ContextMetaKeys.PASSTHROUGH_FIELDS, None)
            retry_data.append(record_copy)

        # Use task preparator to create tasks
        prepared = self._task_preparator.prepare_tasks(
            agent_config=agent_config,
            data=retry_data,
            provider=provider,
            output_directory=output_directory,
            batch_name=retry_batch_name,
        )

        logger.debug(
            "Prepared %d retry tasks for attempt %d",
            prepared.task_count,
            retry_attempt,
        )

        return prepared.tasks, prepared.context_map

    def submit_retry_batch(
        self,
        tasks: List[Dict[str, Any]],
        retry_context: Dict[str, Any],
        parent_batch_id: str,
        retry_attempt: int,
        provider: Any,  # BaseBatchClient
        output_directory: str,
        agent_config: Dict[str, Any],
        original_file_name: str = "default",
    ) -> str:
        """
        Submit a retry batch and update registry.

        Args:
            tasks: Batch tasks to submit
            retry_context: Context map for retry records
            parent_batch_id: ID of parent batch
            retry_attempt: Current retry attempt number
            provider: Batch client
            output_directory: Output directory
            agent_config: Agent configuration
            original_file_name: Original file name for registry key

        Returns:
            New retry batch ID
        """
        retry_batch_name = f"{parent_batch_id}_r{retry_attempt}"

        # Save retry context map
        self._context_manager.save_batch_context_map(
            retry_context, output_directory, retry_batch_name
        )

        # Submit to provider
        batch_id, initial_status = provider.submit_batch(tasks, retry_batch_name, output_directory)

        logger.info(
            "Submitted retry batch %s (attempt %d, %d records)",
            batch_id,
            retry_attempt,
            len(tasks),
        )

        # Create registry entry for retry batch
        retry_file_name = f"{original_file_name}_r{retry_attempt}"
        retry_entry = BatchJobEntry(
            batch_id=batch_id,
            status=initial_status,
            timestamp=datetime.now().isoformat(),
            provider=agent_config.get("model_vendor", "unknown").lower(),
            record_count=len(tasks),
            parent_batch_id=parent_batch_id,
            retry_attempt=retry_attempt,
            retry_for_records=list(retry_context.keys()),
            has_retry_batch=False,
        )
        self._registry_manager.save_batch_job(retry_file_name, retry_entry)

        # Update parent batch to indicate it has a retry
        self._update_parent_has_retry(parent_batch_id)

        return batch_id

    def _update_parent_has_retry(self, parent_batch_id: str) -> None:
        """Update parent batch entry to indicate it has a retry batch."""
        all_jobs = self._registry_manager.get_all_jobs()
        for file_name, entry in all_jobs.items():
            if entry.batch_id == parent_batch_id:
                # Create updated entry with has_retry_batch=True
                updated_entry = BatchJobEntry(
                    batch_id=entry.batch_id,
                    status=entry.status,
                    timestamp=entry.timestamp,
                    provider=entry.provider,
                    record_count=entry.record_count,
                    parent_batch_id=entry.parent_batch_id,
                    retry_attempt=entry.retry_attempt,
                    retry_for_records=entry.retry_for_records,
                    has_retry_batch=True,
                )
                self._registry_manager.save_batch_job(file_name, updated_entry)
                logger.debug("Updated parent batch %s has_retry_batch=True", parent_batch_id)
                return

    def _wait_for_batch_completion(
        self,
        batch_id: str,
        provider: Any,
        _output_directory: str,
    ) -> str:
        """
        Poll until batch reaches terminal state.

        Args:
            batch_id: Batch ID to monitor
            provider: Batch client
            _output_directory: Output directory (reserved for future use)

        Returns:
            Final batch status

        Raises:
            TimeoutError: If max poll attempts exceeded
        """
        for attempt in range(self.MAX_POLL_ATTEMPTS):
            status = provider.check_status(batch_id)

            if status in BatchStatus.terminal_states():
                logger.info("Batch %s reached terminal state: %s", batch_id, status)
                # Update registry
                self._registry_manager.update_status(batch_id, status)
                return status

            logger.debug(
                "Batch %s status: %s, polling again in %ds (attempt %d)",
                batch_id,
                status,
                self._poll_interval,
                attempt + 1,
            )
            time.sleep(self._poll_interval)

        raise TimeoutError(
            f"Batch {batch_id} did not complete within {self.MAX_POLL_ATTEMPTS} poll attempts"
        )

    def orchestrate_retry_chain(
        self,
        original_batch_id: str,
        initial_reconciliation: BatchReconciliationResult,
        context_map: Dict[str, Any],
        agent_config: Dict[str, Any],
        output_directory: str,
        original_file_name: str = "default",
        retry_config: Optional[RetryConfig] = None,
    ) -> RetryChainResult:
        """
        Orchestrate the complete retry chain until exhaustion.

        Main entry point for retry orchestration. Continues retrying
        until all records succeed or max_attempts is reached.

        Args:
            original_batch_id: ID of the original batch
            initial_reconciliation: Reconciliation result from original batch
            context_map: Full context map from original batch
            agent_config: Agent configuration
            output_directory: Output directory
            original_file_name: Original file name for registry
            retry_config: Retry configuration (uses default if not specified)

        Returns:
            RetryChainResult with merged data from all batches
        """
        config = retry_config or get_retry_config(agent_config, self._default_retry_config)

        result = RetryChainResult(
            original_batch_id=original_batch_id,
            total_attempts=0,
            final_success_count=len(initial_reconciliation.processed_ids),
            final_missing_count=len(initial_reconciliation.missing_ids),
        )

        # Track which records need retry
        current_missing_ids = initial_reconciliation.missing_ids.copy()
        current_attempt = 0
        current_parent_id = original_batch_id
        current_context = context_map

        # Get provider for this batch
        provider = self._client_resolver.get_for_batch_id(
            original_batch_id, self._registry_manager, output_directory
        )

        # Retry loop
        while self.should_retry(current_missing_ids, current_attempt, config):
            current_attempt += 1
            result.total_attempts = current_attempt

            # Get records to retry
            retry_context = self.get_retry_records(current_missing_ids, current_context)

            if not retry_context:
                logger.warning("No retry records found in context, stopping retry chain")
                break

            # Prepare retry tasks
            tasks, prepared_context = self.prepare_retry_tasks(
                retry_context=retry_context,
                agent_config=agent_config,
                provider=provider,
                output_directory=output_directory,
                parent_batch_id=current_parent_id,
                retry_attempt=current_attempt,
            )

            if not tasks:
                logger.warning("No tasks prepared for retry, stopping retry chain")
                break

            # Submit retry batch
            retry_batch_id = self.submit_retry_batch(
                tasks=tasks,
                retry_context=prepared_context,
                parent_batch_id=current_parent_id,
                retry_attempt=current_attempt,
                provider=provider,
                output_directory=output_directory,
                agent_config=agent_config,
                original_file_name=original_file_name,
            )
            result.retry_batch_ids.append(retry_batch_id)

            # Wait for retry batch to complete
            final_status = self._wait_for_batch_completion(
                retry_batch_id, provider, output_directory
            )

            if final_status != BatchStatus.COMPLETED:
                logger.error(
                    "Retry batch %s ended with status %s, stopping retry chain",
                    retry_batch_id,
                    final_status,
                )
                break

            # Retrieve and reconcile retry results
            retry_results = provider.retrieve_results(retry_batch_id, output_directory)

            # Import here to avoid circular dependency
            # pylint: disable=import-outside-toplevel
            from agent_actions.llm_invocation.batch.processing.batch_result_reconciler import (
                BatchResultReconciler,
            )

            retry_reconciler = BatchResultReconciler(prepared_context)
            for batch_result in retry_results:
                retry_reconciler.mark_processed(batch_result.custom_id)

            retry_reconciliation = retry_reconciler.reconcile()

            # Update tracking
            succeeded_in_retry = set(prepared_context.keys()) - retry_reconciliation.missing_ids
            result.final_success_count += len(succeeded_in_retry)

            # Prepare for next iteration
            current_missing_ids = retry_reconciliation.missing_ids
            current_parent_id = retry_batch_id
            current_context = prepared_context

            logger.info(
                "Retry attempt %d: %d succeeded, %d still missing",
                current_attempt,
                len(succeeded_in_retry),
                len(current_missing_ids),
            )

        # Final state
        result.final_missing_count = len(current_missing_ids)

        logger.info(
            "Retry chain complete for %s: %d attempts, %d success, %d missing",
            original_batch_id,
            result.total_attempts,
            result.final_success_count,
            result.final_missing_count,
        )

        return result

    def add_retry_metadata_to_record(
        self,
        record: Dict[str, Any],
        original_batch_id: str,
        final_batch_id: str,
        retry_attempts: int,
    ) -> Dict[str, Any]:
        """
        Add retry metadata to a processed record.

        Args:
            record: The processed record
            original_batch_id: ID of the original batch
            final_batch_id: ID of the batch where record succeeded
            retry_attempts: Number of retry attempts (0 = original success)

        Returns:
            Record with _retry_metadata added
        """
        metadata = RetryMetadata(
            was_retried=retry_attempts > 0,
            retry_attempts=retry_attempts,
            original_batch_id=original_batch_id,
            final_batch_id=final_batch_id,
        )
        BatchContextMetadata.set_retry_metadata(record, metadata.to_dict())
        return record
