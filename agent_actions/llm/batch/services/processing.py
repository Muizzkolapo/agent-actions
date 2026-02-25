"""Batch processing service for processing batch job results.

This service encapsulates all result processing functionality, extracted from
BatchService to follow Single Responsibility Principle.

Retry and reprompt logic is delegated to BatchRetryService (retry.py).
Result retrieval with reconciliation is delegated to shared.retrieve_and_reconcile().
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, Any, List, Callable

from agent_actions.logging import fire_event
from agent_actions.storage.backend import (
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_SKIPPED,
)

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.logging.events import BatchCompleteEvent
from agent_actions.processing.types import RecoveryMetadata
from agent_actions.output.writer import FileWriter
from agent_actions.utils.path_utils import ensure_directory_exists
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
)
from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.registry import (
    BatchRegistryManager,
)
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.processing.result_processor import (
    BatchResultProcessor,
)
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.errors import ProcessingError

logger = logging.getLogger(__name__)


class BatchProcessingService:
    """Service for processing batch job results.

    Handles result retrieval, conversion, and output file generation.
    Delegates retry/reprompt logic to BatchRetryService.
    """

    def __init__(
        self,
        client_resolver: BatchClientResolver,
        context_manager: BatchContextManager,
        result_processor: BatchResultProcessor,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
        source_handler: Optional[Any] = None,
        agent_indices: Optional[Dict[str, int]] = None,
        dependency_configs: Optional[Dict[str, Dict]] = None,
        storage_backend: Optional["StorageBackend"] = None,
        action_name: Optional[str] = None,
    ):
        """Initialize processing service with dependencies.

        Args:
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            result_processor: Processor for batch results
            registry_manager_factory: Factory function to create registry managers
            source_handler: Optional handler for source data
            agent_indices: Dict mapping agent names to node indices (for reprompt)
            dependency_configs: Dict mapping dependency names to configs (for reprompt)
            storage_backend: Optional storage backend for database persistence
            action_name: Node name for backend writes (required if storage_backend provided)
        """
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._result_processor = result_processor
        self._registry_manager_factory = registry_manager_factory
        self._source_handler = source_handler
        self._agent_indices = agent_indices or {}
        self._dependency_configs = dependency_configs or {}
        self._storage_backend = storage_backend
        self._action_name = action_name
        self._retry_service = BatchRetryService(
            agent_indices=self._agent_indices,
            dependency_configs=self._dependency_configs,
            storage_backend=self._storage_backend,
        )

    def process_batch_results(
        self,
        batch_id: str,
        output_directory: str,
        base_directory: str,
        file_path: str,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Process batch results and integrate them into workflow output system.

        Args:
            batch_id: Batch job ID
            output_directory: Output directory path
            base_directory: Base directory for relative paths
            file_path: Original input file path
            agent_config: Agent configuration

        Returns:
            Path to output file

        Raises:
            ProcessingError: If batch not completed or processing fails
        """
        try:
            manager = self._registry_manager_factory(output_directory)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

            if provider.check_status(batch_id) != BatchStatus.COMPLETED:
                raise ProcessingError("Batch job is not completed", context={"batch_id": batch_id})

            # Get entry and load context
            entry = manager.get_batch_job_by_id(batch_id)
            file_name = entry.file_name if entry else None
            context_map = (
                self._context_manager.load_batch_context_map(
                    output_directory, file_name or "default"
                )
                if file_name
                else {}
            )
            agent_config = self._apply_workflow_session_id(agent_config, entry)

            # Retrieve and process results
            batch_results = retrieve_and_reconcile(
                provider,
                batch_id,
                output_directory,
                context_map=context_map,
                record_count=entry.record_count if entry else None,
                file_name=file_name,
            )
            processed_data = self._convert_batch_results_to_workflow_format(
                batch_results,
                context_map=context_map,
                output_directory=output_directory,
                agent_config=agent_config,
            )

            # Write per-record dispositions for dead records
            if self._storage_backend and self._action_name:
                self._write_record_dispositions(processed_data, self._action_name)

            # Save source data before writing output
            if self._source_handler:
                self._source_handler.save_task_source(
                    processed_data,
                    file_path,
                    base_directory,
                    output_directory,
                    storage_backend=self._storage_backend,
                )

            # Write output files
            output_file = Path(output_directory) / Path(file_path).relative_to(
                base_directory
            ).with_suffix(".json")
            # Only create directory if not using storage backend
            if self._storage_backend is None:
                ensure_directory_exists(output_file, is_file=True)
            FileWriter(
                str(output_file),
                storage_backend=self._storage_backend,
                action_name=self._action_name,
                output_directory=output_directory,
            ).write_target(processed_data)

            return str(output_file)
        except ProcessingError:
            raise
        except Exception as e:
            raise ProcessingError(
                f"Failed to process batch results to workflow output: {e}", cause=e
            ) from e

    def process_all_batch_results(
        self,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]] = None,
        action_name: Optional[str] = None,
    ) -> List[str]:
        """Process all completed batch jobs in the registry.

        Skips recovery entries (processed via their parent). Tolerates empty
        processed_files when recovery batches are pending (in_progress).

        Args:
            output_directory: Output directory path
            agent_config: Agent configuration
            action_name: Override action_name for storage backend writes (uses self._action_name if not provided)

        Returns:
            List of output file paths

        Raises:
            ProcessingError: If no registry found or no files processed (and no recovery pending)
        """
        manager = self._registry_manager_factory(output_directory)
        all_jobs = manager.get_all_jobs()
        if not all_jobs:
            raise ProcessingError(
                "No batch registry found", context={"output_directory": output_directory}
            )

        # Use provided action_name or fall back to instance default
        effective_action_name = action_name or self._action_name

        processed_files = []
        for file_name, entry in all_jobs.items():
            batch_id = entry.batch_id
            if not batch_id:
                continue

            # Skip recovery entries — processed via their parent
            if entry.parent_file_name is not None:
                continue

            # Check status using helper method
            if not self._is_batch_ready_for_processing(batch_id, output_directory):
                continue

            # Process batch
            try:
                output_file = self._process_single_batch_file(
                    batch_id=batch_id,
                    file_name=file_name,
                    entry=entry,
                    output_directory=output_directory,
                    agent_config=agent_config,
                    manager=manager,
                    action_name=effective_action_name,
                )
                if output_file:
                    processed_files.append(output_file)
            except Exception as e:
                logger.exception(
                    "Failed to process batch %s (%s): %s",
                    batch_id,
                    file_name,
                    e,
                    extra={
                        "batch_id": batch_id,
                        "file_name": file_name,
                        "output_directory": output_directory,
                        "operation": "batch_result_processing",
                        "total_processed": len(processed_files),
                        "registry_size": len(all_jobs),
                    },
                )
                continue

        if not processed_files:
            # Check if recovery batches are pending — not an error
            stats = manager.get_registry_stats()
            if stats.in_progress > 0:
                return processed_files
            raise ProcessingError(
                "No batch results were successfully processed",
                context={"output_directory": output_directory},
            )
        return processed_files

    def _is_batch_ready_for_processing(self, batch_id: str, output_directory: str) -> bool:
        """Check if batch is ready for processing (completed status).

        Args:
            batch_id: The batch job ID to check
            output_directory: Directory containing batch registry

        Returns:
            True if batch status is COMPLETED, False otherwise
        """
        try:
            manager = self._registry_manager_factory(output_directory)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)
            status = provider.check_status(batch_id)
            return status == BatchStatus.COMPLETED
        except Exception as e:
            logger.debug("Failed to check batch status for %s: %s", batch_id, e, exc_info=True)
            return False

    def _determine_output_path(
        self, output_directory: str, file_name: Optional[str], batch_id: str
    ) -> Path:
        """Determine the output file path for batch results.

        Args:
            output_directory: Base output directory
            file_name: Original file name (may be None or "default")
            batch_id: Batch job ID for fallback naming

        Returns:
            Path object for the output file
        """
        if file_name and file_name != "default":
            return Path(output_directory) / f"{Path(file_name).stem}.json"
        return Path(output_directory) / f"{batch_id}_processed_output.json"

    def _write_batch_output(
        self,
        output_file: Path,
        main_output: List[Dict[str, Any]],
        output_directory: str,
        action_name: Optional[str] = None,
    ) -> None:
        """Write batch output file.

        Args:
            output_file: Path to write main output
            main_output: Main output data to write
            output_directory: Output directory path
            action_name: Override action_name for storage backend writes
        """
        # Only create directory if not using storage backend
        if self._storage_backend is None:
            ensure_directory_exists(output_file, is_file=True)
        FileWriter(
            str(output_file),
            storage_backend=self._storage_backend,
            action_name=action_name or self._action_name,
            output_directory=output_directory,
        ).write_target(main_output)

    def _process_single_batch_file(
        self,
        batch_id: str,
        file_name: str,
        entry: BatchJobEntry,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
        action_name: Optional[str] = None,
    ) -> Optional[str]:
        """Process a single batch file and return output path.

        Supports two modes:
        - Branch A: Original batch (no recovery_type) — may trigger async recovery
        - Branch B: Recovery batch (has recovery_type) — processes recovery results

        When recovery is triggered, returns None and registers a new batch entry.
        The workflow re-run loop will detect the new entry and process it later.

        Args:
            batch_id: The batch job ID
            file_name: Original file name
            entry: Batch job registry entry
            output_directory: Output directory path
            agent_config: Agent configuration (may include retry settings)
            manager: Registry manager instance
            action_name: Override action_name for storage backend writes

        Returns:
            Output file path if successful, None if recovery is pending
        """
        # Branch B: Recovery batch — delegate to recovery handler
        if entry.recovery_type is not None:
            return self._process_recovery_batch(
                batch_id=batch_id,
                file_name=file_name,
                entry=entry,
                output_directory=output_directory,
                agent_config=agent_config,
                manager=manager,
                action_name=action_name,
            )

        # Branch A: Original batch
        return self._process_original_batch(
            batch_id=batch_id,
            file_name=file_name,
            entry=entry,
            output_directory=output_directory,
            agent_config=agent_config,
            manager=manager,
            action_name=action_name,
        )

    def _process_original_batch(
        self,
        batch_id: str,
        file_name: str,
        entry: BatchJobEntry,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
        action_name: Optional[str] = None,
    ) -> Optional[str]:
        """Process an original (non-recovery) batch file.

        1. Retrieve results
        2. Check for missing records → submit async retry if needed
        3. Validate results → submit async reprompt if needed
        4. If neither needed → write output

        Returns:
            Output file path if processing is complete, None if recovery batch was submitted
        """
        start_time = time.time()

        context_map = self._context_manager.load_batch_context_map(
            output_directory, file_name or "default"
        )
        agent_config = self._apply_workflow_session_id(agent_config, entry)
        provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

        # Retrieve results
        batch_results = retrieve_and_reconcile(
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=entry.record_count,
            file_name=file_name,
        )

        # Check for retry
        retry_config = (agent_config or {}).get("retry")
        retry_enabled = retry_config and retry_config.get("enabled", True)

        if retry_enabled:
            expected_ids = BatchResultReconciler.collect_expected_custom_ids(context_map)
            received_ids = BatchResultReconciler.collect_result_custom_ids(batch_results)
            missing_ids = expected_ids - received_ids

            if missing_ids:
                max_attempts = retry_config.get("max_attempts", 3) if retry_config else 3
                # Submit async retry batch
                submission = self._retry_service.submit_retry_batch(
                    provider=provider,
                    missing_ids=missing_ids,
                    context_map=context_map,
                    output_directory=output_directory,
                    file_name=file_name,
                    agent_config=agent_config,
                )
                if submission:
                    retry_batch_id, record_count = submission
                    # Register recovery entry
                    recovery_file_name = f"{file_name}_retry_1"
                    recovery_entry = BatchJobEntry(
                        batch_id=retry_batch_id,
                        status=BatchStatus.SUBMITTED,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        provider=entry.provider,
                        record_count=record_count,
                        file_name=recovery_file_name,
                        parent_file_name=file_name,
                        recovery_type="retry",
                        recovery_attempt=1,
                    )
                    manager.save_batch_job(recovery_file_name, recovery_entry)

                    # Save recovery state
                    record_failure_counts = {rid: 1 for rid in missing_ids}
                    state = RecoveryState(
                        phase="retry",
                        retry_attempt=1,
                        retry_max_attempts=max_attempts,
                        missing_ids=list(missing_ids),
                        record_failure_counts=record_failure_counts,
                        accumulated_results=BatchRetryService.serialize_results(batch_results),
                    )
                    # Store reprompt config for later
                    reprompt_config = (agent_config or {}).get("reprompt")
                    if reprompt_config:
                        state.reprompt_max_attempts = reprompt_config.get("max_attempts", 2)
                        state.validation_name = reprompt_config.get("validation")
                        state.on_exhausted = reprompt_config.get("on_exhausted", "return_last")

                    RecoveryStateManager.save(output_directory, file_name, state)
                    logger.info(
                        "Async retry submitted for %s: %d missing records, batch %s",
                        file_name,
                        len(missing_ids),
                        retry_batch_id,
                    )
                    return None  # Recovery pending

        # Check for reprompt (no retry needed or retry not configured)
        should_continue = self._check_and_submit_reprompt(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            entry=entry,
            agent_config=agent_config,
            manager=manager,
            provider=provider,
        )
        if not should_continue:
            return None  # Reprompt submitted, processing paused

        # No recovery needed — process normally
        return self._finalize_batch_output(
            batch_results=batch_results,
            exhausted_recovery=None,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            batch_id=batch_id,
            agent_config=agent_config,
            manager=manager,
            action_name=action_name,
            start_time=start_time,
        )

    def _process_recovery_batch(
        self,
        batch_id: str,
        file_name: str,
        entry: BatchJobEntry,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
        action_name: Optional[str] = None,
    ) -> Optional[str]:
        """Process a recovery batch (retry or reprompt).

        Loads recovery state, merges new results, and determines next action.

        Returns:
            Output file path if processing is complete, None if more recovery is needed
        """
        start_time = time.time()
        parent_file_name = entry.parent_file_name
        if not parent_file_name:
            logger.error("Recovery entry %s has no parent_file_name", file_name)
            return None

        # Load recovery state
        state = RecoveryStateManager.load(output_directory, parent_file_name)
        if not state:
            logger.error("No recovery state found for %s", parent_file_name)
            return None

        context_map = self._context_manager.load_batch_context_map(
            output_directory, parent_file_name
        )
        agent_config = self._apply_workflow_session_id(agent_config, entry)
        provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

        # Retrieve recovery batch results
        recovery_results = retrieve_and_reconcile(
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=entry.record_count,
            file_name=file_name,
        )

        # Deserialize accumulated results
        accumulated = BatchRetryService.deserialize_results(state.accumulated_results)

        if entry.recovery_type == "retry":
            return self._handle_retry_recovery(
                state=state,
                recovery_results=recovery_results,
                accumulated=accumulated,
                context_map=context_map,
                output_directory=output_directory,
                parent_file_name=parent_file_name,
                entry=entry,
                agent_config=agent_config,
                manager=manager,
                provider=provider,
                action_name=action_name,
                start_time=start_time,
            )
        elif entry.recovery_type == "reprompt":
            return self._handle_reprompt_recovery(
                state=state,
                recovery_results=recovery_results,
                accumulated=accumulated,
                context_map=context_map,
                output_directory=output_directory,
                parent_file_name=parent_file_name,
                entry=entry,
                agent_config=agent_config,
                manager=manager,
                provider=provider,
                action_name=action_name,
                start_time=start_time,
            )

        logger.error("Unknown recovery_type: %s", entry.recovery_type)
        return None

    def _handle_retry_recovery(
        self,
        state: RecoveryState,
        recovery_results: List[BatchResult],
        accumulated: List[BatchResult],
        context_map: Dict[str, Any],
        output_directory: str,
        parent_file_name: str,
        entry: BatchJobEntry,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
        provider: Any,
        action_name: Optional[str],
        start_time: float,
    ) -> Optional[str]:
        """Handle retry recovery batch completion."""
        missing_ids = set(state.missing_ids)

        # Process retry results
        merged, still_missing, updated_counts, _ = self._retry_service.process_retry_results(
            results=recovery_results,
            accumulated_results=accumulated,
            context_map=context_map,
            record_failure_counts=state.record_failure_counts,
            missing_ids=missing_ids,
        )

        # Check if more retries needed
        if still_missing and state.retry_attempt < state.retry_max_attempts:
            next_attempt = state.retry_attempt + 1
            submission = self._retry_service.submit_retry_batch(
                provider=provider,
                missing_ids=still_missing,
                context_map=context_map,
                output_directory=output_directory,
                file_name=parent_file_name,
                agent_config=agent_config,
            )
            if submission:
                retry_batch_id, record_count = submission
                recovery_file_name = f"{parent_file_name}_retry_{next_attempt}"
                recovery_entry = BatchJobEntry(
                    batch_id=retry_batch_id,
                    status=BatchStatus.SUBMITTED,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    provider=entry.provider,
                    record_count=record_count,
                    file_name=recovery_file_name,
                    parent_file_name=parent_file_name,
                    recovery_type="retry",
                    recovery_attempt=next_attempt,
                )
                manager.save_batch_job(recovery_file_name, recovery_entry)

                # Update state
                state.retry_attempt = next_attempt
                state.missing_ids = list(still_missing)
                state.record_failure_counts = updated_counts
                state.accumulated_results = BatchRetryService.serialize_results(merged)
                RecoveryStateManager.save(output_directory, parent_file_name, state)
                return None  # More retries pending

        # Build exhausted recovery for still-missing records
        exhausted_recovery = None
        if still_missing:
            exhausted_recovery = self._retry_service.build_exhausted_recovery(
                still_missing, updated_counts
            )

        # Retry phase done — check if reprompt is needed
        should_continue = self._check_and_submit_reprompt(
            batch_results=merged,
            context_map=context_map,
            output_directory=output_directory,
            file_name=parent_file_name,
            entry=entry,
            agent_config=agent_config,
            manager=manager,
            provider=provider,
            recovery_state=state,
            exhausted_recovery=exhausted_recovery,
        )
        if not should_continue:
            return None  # Reprompt submitted, processing paused

        # All done — finalize
        RecoveryStateManager.delete(output_directory, parent_file_name)
        return self._finalize_batch_output(
            batch_results=merged,
            exhausted_recovery=exhausted_recovery,
            context_map=context_map,
            output_directory=output_directory,
            file_name=parent_file_name,
            batch_id=entry.batch_id,
            agent_config=agent_config,
            manager=manager,
            action_name=action_name,
            start_time=start_time,
        )

    def _handle_reprompt_recovery(
        self,
        state: RecoveryState,
        recovery_results: List[BatchResult],
        accumulated: List[BatchResult],
        context_map: Dict[str, Any],
        output_directory: str,
        parent_file_name: str,
        entry: BatchJobEntry,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
        provider: Any,
        action_name: Optional[str],
        start_time: float,
    ) -> Optional[str]:
        """Handle reprompt recovery batch completion."""
        # Merge reprompt results
        merged = self._retry_service.process_reprompt_results(
            reprompt_results=recovery_results,
            accumulated_results=accumulated,
        )

        # Re-validate
        failed_results, validation_name = self._retry_service.validate_results(
            results=merged,
            agent_config=agent_config,
        )

        if failed_results and state.reprompt_attempt < state.reprompt_max_attempts:
            next_attempt = state.reprompt_attempt + 1
            submission = self._retry_service.submit_reprompt_batch(
                provider=provider,
                failed_results=failed_results,
                context_map=context_map,
                output_directory=output_directory,
                file_name=parent_file_name,
                agent_config=agent_config,
                attempt=next_attempt,
            )
            if submission:
                reprompt_batch_id, record_count = submission
                recovery_file_name = f"{parent_file_name}_reprompt_{next_attempt}"
                recovery_entry = BatchJobEntry(
                    batch_id=reprompt_batch_id,
                    status=BatchStatus.SUBMITTED,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    provider=entry.provider,
                    record_count=record_count,
                    file_name=recovery_file_name,
                    parent_file_name=parent_file_name,
                    recovery_type="reprompt",
                    recovery_attempt=next_attempt,
                )
                manager.save_batch_job(recovery_file_name, recovery_entry)

                # Update per-record tracking
                for fr in failed_results:
                    state.reprompt_attempts_per_record[fr.custom_id] = (
                        state.reprompt_attempts_per_record.get(fr.custom_id, 0) + 1
                    )

                state.reprompt_attempt = next_attempt
                state.accumulated_results = BatchRetryService.serialize_results(merged)
                RecoveryStateManager.save(output_directory, parent_file_name, state)
                return None  # More reprompts pending

        # Apply exhaustion metadata if reprompt is done but some failed
        if failed_results and validation_name:
            on_exhausted = state.on_exhausted
            failed_ids = {r.custom_id for r in failed_results}
            merged = self._retry_service.apply_exhausted_reprompt_metadata(
                results=merged,
                failed_ids=failed_ids,
                validation_name=validation_name,
                attempt=state.reprompt_attempt,
                on_exhausted=on_exhausted,
            )

        # Rebuild exhausted_recovery from state if retry had exhausted records.
        # Invariant: state.missing_ids and state.record_failure_counts are frozen
        # at the end of the retry phase (set in _handle_retry_recovery or
        # _check_and_submit_reprompt). The reprompt phase never modifies them —
        # it only tracks reprompt_attempts_per_record for validation failures.
        exhausted_recovery = None
        if state.missing_ids:
            exhausted_recovery = self._retry_service.build_exhausted_recovery(
                set(state.missing_ids), state.record_failure_counts
            )

        # All done — finalize
        RecoveryStateManager.delete(output_directory, parent_file_name)
        return self._finalize_batch_output(
            batch_results=merged,
            exhausted_recovery=exhausted_recovery,
            context_map=context_map,
            output_directory=output_directory,
            file_name=parent_file_name,
            batch_id=entry.batch_id,
            agent_config=agent_config,
            manager=manager,
            action_name=action_name,
            start_time=start_time,
        )

    def _check_and_submit_reprompt(
        self,
        batch_results: List[BatchResult],
        context_map: Dict[str, Any],
        output_directory: str,
        file_name: str,
        entry: BatchJobEntry,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
        provider: Any,
        recovery_state: Optional[RecoveryState] = None,
        exhausted_recovery: Optional[Dict[str, RecoveryMetadata]] = None,
    ) -> bool:
        """Check if reprompt is needed and submit async batch if so.

        Returns:
            True if processing should continue (no reprompt, or reprompt exhausted/failed).
            False if a reprompt batch was submitted (caller should return None).
        """
        reprompt_config = (agent_config or {}).get("reprompt")
        if not reprompt_config:
            return True

        failed_results, validation_name = self._retry_service.validate_results(
            results=batch_results,
            agent_config=agent_config,
        )

        if not failed_results:
            return True

        max_attempts = reprompt_config.get("max_attempts", 2)
        on_exhausted = reprompt_config.get("on_exhausted", "return_last")

        # If this is the first reprompt attempt
        current_attempt = 0
        if recovery_state:
            current_attempt = recovery_state.reprompt_attempt

        if current_attempt >= max_attempts:
            # Exhausted — apply metadata and continue to finalize
            failed_ids = {r.custom_id for r in failed_results}
            self._retry_service.apply_exhausted_reprompt_metadata(
                results=batch_results,
                failed_ids=failed_ids,
                validation_name=validation_name or "",
                attempt=current_attempt,
                on_exhausted=on_exhausted,
            )
            return True

        next_attempt = current_attempt + 1
        submission = self._retry_service.submit_reprompt_batch(
            provider=provider,
            failed_results=failed_results,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            agent_config=agent_config,
            attempt=next_attempt,
        )

        if not submission:
            return True  # Submission failed, continue with current results

        reprompt_batch_id, record_count = submission
        recovery_file_name = f"{file_name}_reprompt_{next_attempt}"
        recovery_entry = BatchJobEntry(
            batch_id=reprompt_batch_id,
            status=BatchStatus.SUBMITTED,
            timestamp=datetime.now(timezone.utc).isoformat(),
            provider=entry.provider,
            record_count=record_count,
            file_name=recovery_file_name,
            parent_file_name=file_name,
            recovery_type="reprompt",
            recovery_attempt=next_attempt,
        )
        manager.save_batch_job(recovery_file_name, recovery_entry)

        # Save/update recovery state
        state = recovery_state or RecoveryState(phase="reprompt")
        state.phase = "reprompt"
        state.reprompt_attempt = next_attempt
        state.reprompt_max_attempts = max_attempts
        state.validation_name = validation_name
        state.on_exhausted = on_exhausted
        for fr in failed_results:
            state.reprompt_attempts_per_record[fr.custom_id] = (
                state.reprompt_attempts_per_record.get(fr.custom_id, 0) + 1
            )
        state.accumulated_results = BatchRetryService.serialize_results(batch_results)

        # Preserve exhausted_recovery info in state
        if exhausted_recovery:
            state.missing_ids = list(exhausted_recovery.keys())
            state.record_failure_counts = {
                rid: meta.retry.failures for rid, meta in exhausted_recovery.items() if meta.retry
            }

        RecoveryStateManager.save(output_directory, file_name, state)
        logger.info(
            "Async reprompt submitted for %s: %d failed records, batch %s",
            file_name,
            len(failed_results),
            reprompt_batch_id,
        )
        return False  # Recovery pending — caller should return None

    def _write_record_dispositions(self, items: List[Dict[str, Any]], action_name: str) -> None:
        """Write dispositions for non-success records in batch output.

        Called from both process_batch_results() (single-batch legacy API) and
        _finalize_batch_output() (multi-batch collection path).  These are
        mutually exclusive entry points — a given batch never flows through both.

        Disposition writes are telemetry — errors are logged but never propagated.
        """
        if not self._storage_backend:
            return
        for item in items:
            source_guid = item.get("source_guid")
            if not source_guid:
                continue
            metadata = item.get("metadata", {})

            try:
                if metadata.get("retry_exhausted"):
                    self._storage_backend.set_disposition(
                        action_name,
                        source_guid,
                        DISPOSITION_EXHAUSTED,
                        reason="retry_exhausted",
                    )
                elif item.get("_unprocessed"):
                    reason = metadata.get("reason", "unprocessed")
                    if metadata.get("skipped_by_where_clause"):
                        disposition = DISPOSITION_FILTERED
                    else:
                        disposition = DISPOSITION_SKIPPED
                    self._storage_backend.set_disposition(
                        action_name,
                        source_guid,
                        disposition,
                        reason=reason,
                    )
                elif item.get("error"):
                    self._storage_backend.set_disposition(
                        action_name,
                        source_guid,
                        DISPOSITION_FAILED,
                        reason=str(item["error"])[:500],
                    )
            except Exception:
                logger.warning(
                    "Failed to write disposition for record %s",
                    source_guid,
                    exc_info=True,
                )

    def _finalize_batch_output(
        self,
        batch_results: List[BatchResult],
        exhausted_recovery: Optional[Dict[str, RecoveryMetadata]],
        context_map: Dict[str, Any],
        output_directory: str,
        file_name: str,
        batch_id: str,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
        action_name: Optional[str],
        start_time: float,
    ) -> str:
        """Finalize batch processing: convert, write output, fire events."""
        processed_data = self._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
            exhausted_recovery=exhausted_recovery,
        )

        # Write per-record dispositions for dead records
        if self._storage_backend and self._action_name:
            self._write_record_dispositions(processed_data, self._action_name)

        output_file = self._determine_output_path(output_directory, file_name, batch_id)
        self._write_batch_output(output_file, processed_data, output_directory, action_name)

        elapsed_time = time.time() - start_time
        total_count = len(batch_results)
        successful_count = sum(1 for r in batch_results if r.success)
        failed_count = total_count - successful_count

        fire_event(
            BatchCompleteEvent(
                batch_id=batch_id,
                agent_name=file_name or "default",
                total=total_count,
                completed=successful_count,
                failed=failed_count,
                elapsed_time=elapsed_time,
            )
        )

        manager.update_status(batch_id, BatchStatus.COMPLETED)

        # Clean up orphaned recovery entries linked to this file
        self._cleanup_recovery_entries(manager, file_name)

        return str(output_file)

    @staticmethod
    def _cleanup_recovery_entries(manager: BatchRegistryManager, parent_file_name: str) -> None:
        """Remove completed recovery entries linked to a parent batch file.

        Prevents orphaned registry entries from accumulating when recovery
        batches are superseded or finalization completes.
        """
        all_jobs = manager.get_all_jobs()
        to_remove = [
            name for name, entry in all_jobs.items() if entry.parent_file_name == parent_file_name
        ]
        for name in to_remove:
            manager.remove_batch_job(name)

    def _convert_batch_results_to_workflow_format(
        self,
        batch_results: List[BatchResult],
        *,
        context_map: Optional[Dict[str, Any]] = None,
        output_directory: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
        exhausted_recovery: Optional[Dict[str, RecoveryMetadata]] = None,
    ) -> List[Dict[str, Any]]:
        """Convert batch results to workflow format.

        Args:
            batch_results: Raw batch results
            context_map: Context map for processing
            output_directory: Output directory path
            agent_config: Agent configuration
            exhausted_recovery: Per-record recovery metadata for exhausted records (custom_id -> RecoveryMetadata)

        Returns:
            Processed results in workflow format
        """
        return self._result_processor.process(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
            exhausted_recovery=exhausted_recovery,
        )

    @staticmethod
    def _apply_workflow_session_id(
        agent_config: Optional[Dict[str, Any]],
        entry: Optional[BatchJobEntry],
    ) -> Optional[Dict[str, Any]]:
        """
        Preserve workflow context used at batch submission time.

        Ensures deterministic version correlation across resumed batch processing
        by restoring workflow_session_id, is_versioned_agent, and version_base_name.
        """
        if not entry:
            return agent_config

        # Create config if None (batch collect mode without agent_config)
        updated_config = agent_config.copy() if agent_config else {}

        # Restore workflow session ID
        if entry.workflow_session_id:
            updated_config["workflow_session_id"] = entry.workflow_session_id

        # Restore version context for loop correlation
        if entry.is_versioned_agent is not None:
            updated_config["is_versioned_agent"] = entry.is_versioned_agent
        if entry.version_base_name is not None:
            updated_config["version_base_name"] = entry.version_base_name

        return updated_config if updated_config else None
