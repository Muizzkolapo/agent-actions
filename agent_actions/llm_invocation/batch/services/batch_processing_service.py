"""Batch processing service for processing batch job results.

This service encapsulates all result processing functionality, extracted from
BatchService to follow Single Responsibility Principle.

Includes retry support for missing records in batch results.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Set

from agent_actions.core.types import RecoveryMetadata, RetryMetadata
from agent_actions.file_io.file_writer import FileWriter
from agent_actions.utilities.path_utils import ensure_directory_exists, create_side_output_directory
from agent_actions.llm_invocation.batch.core.batch_constants import BatchStatus
from agent_actions.llm_invocation.batch.infrastructure.batch_context_manager import (
    BatchContextManager,
)
from agent_actions.llm_invocation.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm_invocation.batch.infrastructure.batch_registry_manager import (
    BatchRegistryManager,
)
from agent_actions.llm_invocation.batch.processing.batch_result_processor import (
    BatchResultProcessor,
)
from agent_actions.llm_invocation.batch.processing.batch_side_output_handler import (
    BatchSideOutputHandler,
)
from agent_actions.llm_invocation.batch.core.batch_models import BatchJobEntry
from agent_actions.llm_invocation.providers.batch_client_base import BaseBatchClient, BatchResult
from agent_actions.errors import ProcessingError

logger = logging.getLogger(__name__)


class BatchProcessingService:
    """Service for processing batch job results.

    Handles result retrieval, conversion, and output file generation.
    """

    def __init__(
        self,
        client_resolver: BatchClientResolver,
        context_manager: BatchContextManager,
        result_processor: BatchResultProcessor,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
        source_handler: Optional[Any] = None,
    ):
        """Initialize processing service with dependencies.

        Args:
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            result_processor: Processor for batch results
            registry_manager_factory: Factory function to create registry managers
            source_handler: Optional handler for source data
        """
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._result_processor = result_processor
        self._registry_manager_factory = registry_manager_factory
        self._source_handler = source_handler

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

            # Retrieve and process results
            batch_results = self._retrieve_results(
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
            main_output, side_output_data = BatchSideOutputHandler.separate(processed_data)

            # Save source data before writing output
            if self._source_handler:
                self._source_handler.save_task_source(
                    main_output, file_path, base_directory, output_directory
                )

            # Write output files
            output_file = Path(output_directory) / Path(file_path).relative_to(
                base_directory
            ).with_suffix(".json")
            ensure_directory_exists(output_file, is_file=True)
            FileWriter(str(output_file)).write_target(main_output)

            if side_output_data:
                side_output_file = (
                    create_side_output_directory(output_directory)
                    / Path(file_path).relative_to(base_directory).name
                )
                BatchSideOutputHandler.save(side_output_data, side_output_file)

            return str(output_file)
        except ProcessingError:
            raise
        except Exception as e:
            raise ProcessingError(
                f"Failed to process batch results to workflow output: {e}", cause=e
            ) from e

    def process_all_batch_results(
        self, output_directory: str, agent_config: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Process all completed batch jobs in the registry.

        Args:
            output_directory: Output directory path
            agent_config: Agent configuration

        Returns:
            List of output file paths

        Raises:
            ProcessingError: If no registry found or no files processed
        """
        manager = self._registry_manager_factory(output_directory)
        all_jobs = manager.get_all_jobs()
        if not all_jobs:
            raise ProcessingError(
                "No batch registry found", context={"output_directory": output_directory}
            )

        processed_files = []
        for file_name, entry in all_jobs.items():
            batch_id = entry.batch_id
            if not batch_id:
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
        except Exception:
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
        side_output_data: Optional[List[Dict[str, Any]]],
        output_directory: str,
    ) -> None:
        """Write main and side output files.

        Args:
            output_file: Path to write main output
            main_output: Main output data to write
            side_output_data: Optional side output data
            output_directory: Directory for side output
        """
        ensure_directory_exists(output_file, is_file=True)
        FileWriter(str(output_file)).write_target(main_output)

        if side_output_data:
            side_output_dir = create_side_output_directory(output_directory)
            side_output_file = side_output_dir / output_file.name
            BatchSideOutputHandler.save(side_output_data, side_output_file)

    def _process_single_batch_file(
        self,
        batch_id: str,
        file_name: str,
        entry: BatchJobEntry,
        output_directory: str,
        agent_config: Optional[Dict[str, Any]],
        manager: BatchRegistryManager,
    ) -> Optional[str]:
        """Process a single batch file and return output path.

        Supports retry for missing records if retry is enabled in agent_config.

        Args:
            batch_id: The batch job ID
            file_name: Original file name
            entry: Batch job registry entry
            output_directory: Output directory path
            agent_config: Agent configuration (may include retry settings)
            manager: Registry manager instance

        Returns:
            Output file path if successful, None if no results
        """
        context_map = self._context_manager.load_batch_context_map(
            output_directory, file_name or "default"
        )
        provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

        # Use retry-aware retrieval if agent_config has retry enabled
        retry_config = (agent_config or {}).get("retry")
        if retry_config and retry_config.get("enabled", True):
            batch_results, exhausted_recovery = self._retrieve_results_with_retry(
                provider,
                batch_id,
                output_directory,
                context_map=context_map,
                record_count=entry.record_count,
                file_name=file_name,
                agent_config=agent_config,
            )
        else:
            batch_results = self._retrieve_results(
                provider,
                batch_id,
                output_directory,
                context_map=context_map,
                record_count=entry.record_count,
                file_name=file_name,
            )
            exhausted_recovery = None

        # Convert results to workflow format
        # exhausted_recovery is a dict mapping custom_id -> RecoveryMetadata for records that never succeeded
        processed_data = self._convert_batch_results_to_workflow_format(
            batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
            exhausted_recovery=exhausted_recovery,
        )

        # Recovery metadata is now handled per-record:
        # - Retried records: _process_successful_result adds _recovery from BatchResult.recovery_metadata
        # - Missing/passthrough records: _stage_6_merge_passthroughs adds _recovery from exhausted_recovery dict
        # - First-try successes: No _recovery (correct - they didn't need retry)

        main_output, side_output_data = BatchSideOutputHandler.separate(processed_data)

        # Determine output path and write files
        output_file = self._determine_output_path(output_directory, file_name, batch_id)
        self._write_batch_output(output_file, main_output, side_output_data, output_directory)

        # Log completion
        logger.info(
            "Batch job completed and processed",
            extra={
                "operation": "process_batch_results",
                "batch_id": batch_id,
                "file_name": file_name,
                "results_count": len(batch_results),
                "main_output_count": (len(main_output) if isinstance(main_output, list) else 1),
                "side_output_count": len(side_output_data) if side_output_data else 0,
                "output_file": str(output_file),
            },
        )

        return str(output_file)

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
        from agent_actions.llm_invocation.batch.processing.batch_result_reconciler import (
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

    def _retrieve_results_with_retry(
        self,
        provider: BaseBatchClient,
        batch_id: str,
        output_directory: str,
        *,
        context_map: Dict[str, Any],
        record_count: Optional[int] = None,
        file_name: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> tuple[List[BatchResult], Optional[Dict[str, RecoveryMetadata]]]:
        """Retrieve batch results with retry for missing records.

        If retry is enabled and records are missing, resubmits missing records
        as a new batch and consolidates results.

        Args:
            provider: Batch API client
            batch_id: Batch job ID
            output_directory: Output directory path
            context_map: Context map for reconciliation and record lookup
            record_count: Expected record count
            file_name: Original file name
            agent_config: Agent configuration with retry settings

        Returns:
            Tuple of (consolidated batch results, per-record recovery metadata for exhausted records)
            The dict maps custom_id -> RecoveryMetadata for records that never succeeded.
        """
        from agent_actions.llm_invocation.batch.processing.batch_result_reconciler import (
            BatchResultReconciler,
        )

        # Get retry config
        retry_config = (agent_config or {}).get("retry")
        retry_enabled = retry_config and retry_config.get("enabled", True)
        max_attempts = retry_config.get("max_attempts", 3) if retry_config else 3

        # Initial retrieval
        all_results = self._retrieve_results(
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=record_count,
            file_name=file_name,
        )

        if not retry_enabled:
            return all_results, None

        # Check for missing records
        expected_ids = BatchResultReconciler.collect_expected_custom_ids(context_map)
        received_ids = BatchResultReconciler.collect_result_custom_ids(all_results)
        missing_ids = expected_ids - received_ids

        if not missing_ids:
            return all_results, None

        # Per-record failure tracking: each record tracks its own failure count
        # Initial failure = 1 (the initial batch didn't return this record)
        record_failure_counts: Dict[str, int] = {rid: 1 for rid in missing_ids}

        # Retry loop for missing records
        retry_attempts = 0

        while missing_ids and retry_attempts < max_attempts:
            retry_attempts += 1
            logger.info(
                "Batch retry attempt %d/%d: resubmitting %d missing records",
                retry_attempts,
                max_attempts,
                len(missing_ids),
            )

            # Resubmit missing records
            retry_results = self._resubmit_missing_records(
                provider=provider,
                missing_ids=missing_ids,
                context_map=context_map,
                output_directory=output_directory,
                file_name=file_name,
                agent_config=agent_config,
            )

            if retry_results:
                # Attach per-record recovery metadata based on individual failure counts
                for res in retry_results:
                    if res.success:
                        custom_id = res.custom_id
                        failures = record_failure_counts.get(custom_id, 1)
                        res.recovery_metadata = RecoveryMetadata(
                            retry=RetryMetadata(
                                attempts=failures + 1,  # failures + 1 success
                                failures=failures,
                                succeeded=True,
                                reason="missing",
                                timestamp=datetime.now(timezone.utc).isoformat(),
                            )
                        )

                # Merge results
                all_results.extend(retry_results)

                # Update missing IDs and increment failure counts for still-missing records
                new_received = BatchResultReconciler.collect_result_custom_ids(retry_results)
                missing_ids = missing_ids - new_received

            # Increment failure count for records that are still missing after this retry
            for rid in missing_ids:
                record_failure_counts[rid] = record_failure_counts.get(rid, 0) + 1

        # Build per-record recovery metadata for exhausted records (still missing after all retries)
        # This is used by passthrough processing for records that never succeeded
        exhausted_recovery: Optional[Dict[str, RecoveryMetadata]] = None
        if retry_attempts > 0 and missing_ids:
            exhausted_recovery = {}
            for rid in missing_ids:
                failures = record_failure_counts.get(rid, 1)
                # For exhausted records: attempts = failures (no successful attempt to add)
                exhausted_recovery[rid] = RecoveryMetadata(
                    retry=RetryMetadata(
                        attempts=failures,
                        failures=failures,
                        succeeded=False,
                        reason="missing",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                )
            logger.warning(
                "Batch retry exhausted: %d records still missing after %d attempts",
                len(missing_ids),
                retry_attempts,
            )

        # Phase 2: Validate and reprompt (after retry completes)
        # Only validate successful results - skip retry-exhausted records
        all_results = self._validate_and_reprompt(
            results=all_results,
            provider=provider,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            agent_config=agent_config,
        )

        return all_results, exhausted_recovery

    def _resubmit_missing_records(
        self,
        provider: BaseBatchClient,
        missing_ids: Set[str],
        context_map: Dict[str, Any],
        output_directory: str,
        file_name: Optional[str],
        agent_config: Optional[Dict[str, Any]],
    ) -> List[BatchResult]:
        """Resubmit missing records as a new batch and wait for completion.

        Args:
            provider: Batch API client
            missing_ids: Set of custom_ids that are missing
            context_map: Context map with original record data
            output_directory: Output directory path
            file_name: Original file name
            agent_config: Agent configuration

        Returns:
            List of batch results from retry batch
        """
        from agent_actions.llm_invocation.batch.processing.batch_task_preparator import (
            BatchTaskPreparator,
        )

        # Extract missing records from context_map
        missing_records = []
        for custom_id in missing_ids:
            if custom_id in context_map:
                record = context_map[custom_id].copy()
                # Ensure target_id is set for task preparation
                if "target_id" not in record:
                    record["target_id"] = custom_id
                missing_records.append(record)

        if not missing_records:
            logger.warning("No records found in context_map for missing IDs")
            return []

        try:
            # Prepare tasks for missing records
            preparator = BatchTaskPreparator()
            prepared = preparator.prepare_tasks(
                agent_config=agent_config or {},
                data=missing_records,
                provider=provider,
                output_directory=output_directory,
                batch_name=f"{file_name}_retry" if file_name else "retry",
            )

            if not prepared.tasks:
                logger.warning("No tasks prepared for retry batch")
                return []

            # Submit retry batch
            batch_name = f"{file_name}_retry" if file_name else "retry"
            retry_batch_id, _ = provider.submit_batch(
                tasks=prepared.tasks,
                batch_name=batch_name,
                output_directory=output_directory,
            )
            logger.info(
                "Retry batch submitted: %s with %d records",
                retry_batch_id,
                len(prepared.tasks),
            )

            # Wait for completion (simple polling)
            status = self._wait_for_batch_completion(provider, retry_batch_id)
            if status != BatchStatus.COMPLETED:
                logger.warning(
                    "Retry batch %s did not complete successfully: %s",
                    retry_batch_id,
                    status,
                )
                return []

            # Retrieve results
            return provider.retrieve_results(retry_batch_id, output_directory)

        except Exception as e:
            logger.warning("Failed to resubmit missing records: %s", e)
            return []

    def _wait_for_batch_completion(
        self,
        provider: BaseBatchClient,
        batch_id: str,
        timeout_seconds: int = 3600,
        poll_interval: int = 30,
    ) -> BatchStatus:
        """Wait for batch to complete with polling.

        Args:
            provider: Batch API client
            batch_id: Batch job ID
            timeout_seconds: Maximum time to wait (default 1 hour)
            poll_interval: Seconds between status checks

        Returns:
            Final batch status
        """
        start_time = time.time()
        while (time.time() - start_time) < timeout_seconds:
            status = provider.check_status(batch_id)
            if status in (BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.CANCELLED):
                return status
            logger.debug("Retry batch %s status: %s, waiting...", batch_id, status)
            time.sleep(poll_interval)

        logger.warning("Retry batch %s timed out after %d seconds", batch_id, timeout_seconds)
        return provider.check_status(batch_id)

    def _validate_and_reprompt(
        self,
        results: List[BatchResult],
        provider: BaseBatchClient,
        context_map: Dict[str, Any],
        output_directory: str,
        file_name: Optional[str],
        agent_config: Optional[Dict[str, Any]],
    ) -> List[BatchResult]:
        """Validate results and reprompt failures with feedback.

        Validates batch results using configured UDF. Records that fail validation
        are resubmitted with feedback messages appended to their prompts.

        Args:
            results: Initial batch results to validate
            provider: Batch API client
            context_map: Context map for record lookup
            output_directory: Output directory path
            file_name: Original file name
            agent_config: Agent configuration with reprompt settings

        Returns:
            Consolidated list of batch results (original passes + reprompt results)
        """
        from agent_actions.core.reprompt_validation import get_validation_function
        from agent_actions.core.types import RepromptMetadata
        from agent_actions.llm_invocation.batch.processing.batch_task_preparator import (
            BatchTaskPreparator,
        )

        # Check if reprompt is enabled
        reprompt_config = (agent_config or {}).get("reprompt")
        if not reprompt_config:
            return results

        validation_name = reprompt_config.get("validation")
        if not validation_name:
            logger.warning("Reprompt enabled but no validation UDF specified")
            return results

        max_attempts = reprompt_config.get("max_attempts", 2)
        on_exhausted = reprompt_config.get("on_exhausted", "return_last")

        # Get validation function
        try:
            validation_func, feedback_message = get_validation_function(validation_name)
        except ValueError as e:
            logger.error("Failed to get validation function: %s", e)
            return results

        # Track per-record reprompt attempts (counts how many times each record failed)
        reprompt_attempts: Dict[str, int] = {}

        # Track final validation status for each record (to avoid double validation calls)
        validation_status: Dict[str, bool] = {}

        # Track which results have been replaced (for consolidation)
        result_map = {r.custom_id: r for r in results}

        attempt = 0
        while attempt < max_attempts:
            attempt += 1

            # Validate all current results
            failed_results = []
            for result in result_map.values():
                # Skip if already failed (not success)
                if not result.success:
                    continue

                # Skip if this result already passed reprompt validation
                if (
                    result.recovery_metadata
                    and result.recovery_metadata.reprompt
                    and result.recovery_metadata.reprompt.passed
                ):
                    continue

                # Validate
                try:
                    is_valid = validation_func(result.content)
                except Exception as e:
                    logger.warning(
                        "Validation UDF error for %s (treating as failure): %s",
                        result.custom_id,
                        e,
                        exc_info=True,
                    )
                    is_valid = False

                # Store validation status for this record (avoids double validation later)
                validation_status[result.custom_id] = is_valid

                if not is_valid:
                    failed_results.append(result)

            # Check if all passed
            if not failed_results:
                logger.info("All %d records passed validation", len(result_map))
                break

            logger.warning(
                "Reprompt attempt %d/%d: %d records failed validation",
                attempt,
                max_attempts,
                len(failed_results),
            )

            # Track attempts for failed records (increment count per record)
            for failed_result in failed_results:
                # Increment the count for this record each time it fails
                reprompt_attempts[failed_result.custom_id] = (
                    reprompt_attempts.get(failed_result.custom_id, 0) + 1
                )

            # Check if exhausted
            if attempt >= max_attempts:
                # Handle exhausted records
                for failed_result in failed_results:
                    if on_exhausted == "raise":
                        raise RuntimeError(
                            f"Reprompt validation exhausted for {failed_result.custom_id} "
                            f"after {attempt} attempts (validation: {validation_name})"
                        )

                    # on_exhausted = "return_last": Add metadata but keep last response
                    if not failed_result.recovery_metadata:
                        failed_result.recovery_metadata = RecoveryMetadata()

                    failed_result.recovery_metadata.reprompt = RepromptMetadata(
                        attempts=attempt,
                        passed=False,
                        validation=validation_name,
                    )
                break

            # Build reprompt tasks for failed records
            reprompt_records = []
            for failed_result in failed_results:
                custom_id = failed_result.custom_id

                # Get original record from context_map
                if custom_id not in context_map:
                    logger.warning(
                        "Cannot reprompt %s: not found in context_map",
                        custom_id,
                    )
                    continue

                original_record = context_map[custom_id].copy()

                # Build feedback message
                feedback = self._build_reprompt_feedback(
                    failed_response=failed_result.content,
                    feedback_message=feedback_message,
                )

                # Append feedback to user_content
                original_user_content = original_record.get("user_content", "")
                original_record["user_content"] = f"{original_user_content}\n\n{feedback}"

                # Ensure target_id is set
                if "target_id" not in original_record:
                    original_record["target_id"] = custom_id

                reprompt_records.append(original_record)

            if not reprompt_records:
                logger.warning("No records to reprompt")
                break

            # Submit reprompt batch
            try:
                reprompt_batch_name = f"{file_name or 'batch'}_reprompt_{attempt}"
                preparator = BatchTaskPreparator()
                result = preparator.prepare_tasks(
                    agent_config=agent_config or {},
                    data=reprompt_records,
                    provider=provider,
                    output_directory=output_directory,
                    batch_name=reprompt_batch_name,
                )

                batch_id, status = provider.submit_batch(
                    tasks=result.tasks,
                    batch_name=reprompt_batch_name,
                    output_directory=output_directory,
                )

                logger.info(
                    "Submitted reprompt batch %s with %d records",
                    batch_id,
                    len(result.tasks),
                )

                # Wait for completion
                final_status = self._wait_for_batch(provider, batch_id)

                if final_status != BatchStatus.COMPLETED:
                    logger.error(
                        "Reprompt batch %s did not complete: %s",
                        batch_id,
                        final_status,
                    )
                    break

                # Retrieve reprompt results
                reprompt_results = provider.retrieve_results(batch_id, output_directory)

                # Replace failed results with reprompt results, preserving existing recovery metadata
                for reprompt_result in reprompt_results:
                    # Preserve existing recovery metadata (e.g., retry metadata)
                    if reprompt_result.custom_id in result_map:
                        existing_recovery = result_map[reprompt_result.custom_id].recovery_metadata

                        # Always ensure recovery_metadata exists on the new result
                        if not reprompt_result.recovery_metadata:
                            reprompt_result.recovery_metadata = RecoveryMetadata()

                        # Merge existing retry metadata if present
                        if existing_recovery and existing_recovery.retry:
                            reprompt_result.recovery_metadata.retry = existing_recovery.retry

                    result_map[reprompt_result.custom_id] = reprompt_result

            except Exception as e:
                logger.error("Error during reprompt batch submission: %s", e)
                break

        # Add reprompt metadata to all records that were reprompted
        for custom_id, attempts in reprompt_attempts.items():
            if custom_id in result_map:
                result = result_map[custom_id]

                # Use cached validation status (avoids redundant validation call)
                passed = validation_status.get(custom_id, False)

                # Add or update recovery metadata
                if not result.recovery_metadata:
                    result.recovery_metadata = RecoveryMetadata()

                result.recovery_metadata.reprompt = RepromptMetadata(
                    attempts=attempts,
                    passed=passed,
                    validation=validation_name,
                )

        return list(result_map.values())

    def _build_reprompt_feedback(self, failed_response: Any, feedback_message: str) -> str:
        """Build feedback message for reprompt batch.

        Args:
            failed_response: The response that failed validation
            feedback_message: Message from validation UDF decorator

        Returns:
            Formatted feedback message
        """
        import json

        try:
            response_str = json.dumps(failed_response, indent=2)
        except Exception:
            response_str = str(failed_response)

        return f"""---
Your response failed validation: {feedback_message}

Your response: {response_str}

Please correct and respond again."""
