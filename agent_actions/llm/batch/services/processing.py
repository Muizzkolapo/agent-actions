"""Batch processing service for converting batch results to workflow output."""

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.errors import ProcessingError
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
)
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.infrastructure.registry import (
    BatchRegistryManager,
)
from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services.processing_recovery import (
    check_and_submit_reprompt as _check_and_submit_reprompt_impl,
)
from agent_actions.llm.batch.services.processing_recovery import (
    finalize_batch_output as _finalize_batch_output_impl,
)
from agent_actions.llm.batch.services.processing_recovery import (
    process_recovery_batch as _process_recovery_batch_impl,
)
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.writer import FileWriter
from agent_actions.processing.result_collector import (
    write_record_dispositions as _write_record_dispositions_impl,
)
from agent_actions.processing.types import RecoveryMetadata
from agent_actions.utils.path_utils import ensure_directory_exists

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
        result_processor: BatchResultStrategy,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
        source_handler: Any | None = None,
        action_indices: dict[str, int] | None = None,
        dependency_configs: dict[str, dict] | None = None,
        storage_backend: Optional["StorageBackend"] = None,
        action_name: str | None = None,
    ):
        """Initialize processing service with dependencies.

        Args:
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            result_processor: Processor for batch results
            registry_manager_factory: Factory function to create registry managers
            source_handler: Optional handler for source data
            action_indices: Dict mapping agent names to node indices (for reprompt)
            dependency_configs: Dict mapping dependency names to configs (for reprompt)
            storage_backend: Optional storage backend for database persistence
            action_name: Node name for backend writes (required if storage_backend provided)
        """
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._result_processor = result_processor
        self._registry_manager_factory = registry_manager_factory
        self._source_handler = source_handler
        self._action_indices = action_indices or {}
        self._dependency_configs = dependency_configs or {}
        self._storage_backend = storage_backend
        self._action_name = action_name
        self._retry_service = BatchRetryService(
            action_indices=self._action_indices,
            dependency_configs=self._dependency_configs,
            storage_backend=self._storage_backend,
        )

    def process_batch_results(
        self,
        batch_id: str,
        output_directory: str,
        base_directory: str,
        file_path: str,
        agent_config: dict[str, Any] | None = None,
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

            if self._storage_backend and self._action_name:
                self._write_record_dispositions(processed_data, self._action_name)
                self._update_prompt_trace_responses(processed_data, self._action_name)

            if self._source_handler:
                self._source_handler.save_task_source(
                    processed_data,
                    file_path,
                    base_directory,
                    output_directory,
                    storage_backend=self._storage_backend,
                )

            output_file = Path(output_directory) / Path(file_path).relative_to(
                base_directory
            ).with_suffix(".json")
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
        agent_config: dict[str, Any] | None = None,
        action_name: str | None = None,
    ) -> list[str]:
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

        effective_action_name = action_name or self._action_name

        processed_files = []
        for file_name, entry in all_jobs.items():
            batch_id = entry.batch_id
            if not batch_id:
                continue

            # Skip recovery entries — processed via their parent
            if entry.parent_file_name is not None:
                continue

            if not self._is_batch_ready_for_processing(batch_id, output_directory):
                continue

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
        self, output_directory: str, file_name: str | None, batch_id: str
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
        main_output: list[dict[str, Any]],
        output_directory: str,
        action_name: str | None = None,
    ) -> None:
        """Write batch output file.

        Args:
            output_file: Path to write main output
            main_output: Main output data to write
            output_directory: Output directory path
            action_name: Override action_name for storage backend writes
        """
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
        agent_config: dict[str, Any] | None,
        manager: BatchRegistryManager,
        action_name: str | None = None,
    ) -> str | None:
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
        agent_config: dict[str, Any] | None,
        manager: BatchRegistryManager,
        action_name: str | None = None,
    ) -> str | None:
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

        batch_results = retrieve_and_reconcile(
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=entry.record_count,
            file_name=file_name,
        )

        retry_config = (agent_config or {}).get("retry")
        retry_enabled = retry_config and retry_config.get("enabled", True)

        if retry_enabled:
            expected_ids = BatchResultReconciler.collect_expected_custom_ids(context_map)
            received_ids = BatchResultReconciler.collect_result_custom_ids(batch_results)
            missing_ids = expected_ids - received_ids

            if missing_ids:
                max_attempts = retry_config.get("max_attempts", 3) if retry_config else 3
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
                        timestamp=datetime.now(UTC).isoformat(),
                        provider=entry.provider,
                        record_count=record_count,
                        file_name=recovery_file_name,
                        parent_file_name=file_name,
                        recovery_type="retry",
                        recovery_attempt=1,
                    )
                    manager.save_batch_job(recovery_file_name, recovery_entry)

                    record_failure_counts = {rid: 1 for rid in missing_ids}
                    state = RecoveryState(
                        phase="retry",
                        retry_attempt=1,
                        retry_max_attempts=max_attempts,
                        missing_ids=list(missing_ids),
                        record_failure_counts=record_failure_counts,
                        accumulated_results=BatchRetryService.serialize_results(batch_results),
                    )
                    from agent_actions.processing.recovery.reprompt import parse_reprompt_config

                    reprompt_parsed = parse_reprompt_config((agent_config or {}).get("reprompt"))
                    if reprompt_parsed:
                        state.reprompt_max_attempts = reprompt_parsed.max_attempts
                        state.validation_name = reprompt_parsed.validation_name
                        state.on_exhausted = reprompt_parsed.on_exhausted

                    RecoveryStateManager.save(output_directory, file_name, state)
                    logger.info(
                        "Async retry submitted for %s: %d missing records, batch %s",
                        file_name,
                        len(missing_ids),
                        retry_batch_id,
                    )
                    return None  # Recovery pending

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

    # =========================================================================
    # DELEGATORS — bodies live in processing_recovery.py
    # =========================================================================

    def _process_recovery_batch(
        self,
        batch_id: str,
        file_name: str,
        entry: BatchJobEntry,
        output_directory: str,
        agent_config: dict[str, Any] | None,
        manager: BatchRegistryManager,
        action_name: str | None = None,
    ) -> str | None:
        """Process a recovery batch (retry or reprompt).

        Delegates to processing_recovery.process_recovery_batch.
        """
        return _process_recovery_batch_impl(
            self,
            batch_id=batch_id,
            file_name=file_name,
            entry=entry,
            output_directory=output_directory,
            agent_config=agent_config,
            manager=manager,
            action_name=action_name,
        )

    def _check_and_submit_reprompt(
        self,
        batch_results: list[BatchResult],
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str,
        entry: BatchJobEntry,
        agent_config: dict[str, Any] | None,
        manager: BatchRegistryManager,
        provider: Any,
        recovery_state: RecoveryState | None = None,
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    ) -> bool:
        """Check if reprompt is needed and submit async batch if so.

        Delegates to processing_recovery.check_and_submit_reprompt.
        """
        return _check_and_submit_reprompt_impl(
            self,
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            entry=entry,
            agent_config=agent_config,
            manager=manager,
            provider=provider,
            recovery_state=recovery_state,
            exhausted_recovery=exhausted_recovery,
        )

    def _finalize_batch_output(
        self,
        batch_results: list[BatchResult],
        exhausted_recovery: dict[str, RecoveryMetadata] | None,
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str,
        batch_id: str,
        agent_config: dict[str, Any] | None,
        manager: BatchRegistryManager,
        action_name: str | None,
        start_time: float,
    ) -> str:
        """Finalize batch processing: convert, write output, fire events.

        Delegates to processing_recovery.finalize_batch_output.
        """
        return _finalize_batch_output_impl(
            self,
            batch_results=batch_results,
            exhausted_recovery=exhausted_recovery,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            batch_id=batch_id,
            agent_config=agent_config,
            manager=manager,
            action_name=action_name,
            start_time=start_time,
        )

    def _write_record_dispositions(self, items: list[dict[str, Any]], action_name: str) -> None:
        """Write dispositions for non-success records in batch output.

        Delegates to result_collector.write_record_dispositions.
        """
        _write_record_dispositions_impl(self._storage_backend, items, action_name)

    def _update_prompt_trace_responses(self, items: list[dict[str, Any]], action_name: str) -> None:
        """Update prompt traces with batch responses. Telemetry — non-fatal."""
        if not self._storage_backend:
            return
        try:
            for item in items:
                source_guid = item.get("source_guid")
                if not source_guid:
                    continue
                content = item.get("content")
                if content is None:
                    continue
                response_text = json.dumps(content, ensure_ascii=False, default=str)
                self._storage_backend.update_prompt_trace_response(
                    action_name=action_name,
                    record_id=source_guid,
                    response_text=response_text,
                )
        except Exception:
            logger.warning(
                "Failed to update prompt trace responses for batch action=%s",
                action_name,
                exc_info=True,
            )

    # =========================================================================
    # HELPERS (kept in this module)
    # =========================================================================

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
        batch_results: list[BatchResult],
        *,
        context_map: dict[str, Any] | None = None,
        output_directory: str | None = None,
        agent_config: dict[str, Any] | None = None,
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    ) -> list[dict[str, Any]]:
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
        results = self._result_processor.process(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
            exhausted_recovery=exhausted_recovery,
        )
        # Flatten ProcessingResult objects to workflow-format dicts.
        return [item for result in results for item in (result.data or [])]

    @staticmethod
    def _apply_workflow_session_id(
        agent_config: dict[str, Any] | None,
        entry: BatchJobEntry | None,
    ) -> dict[str, Any] | None:
        """
        Preserve workflow context used at batch submission time.

        Ensures deterministic version correlation across resumed batch processing
        by restoring workflow_session_id, is_versioned_agent, and version_base_name.
        """
        if not entry:
            return agent_config

        updated_config = agent_config.copy() if agent_config else {}

        if entry.workflow_session_id:
            updated_config["workflow_session_id"] = entry.workflow_session_id

        if entry.is_versioned_agent is not None:
            updated_config["is_versioned_agent"] = entry.is_versioned_agent
        if entry.version_base_name is not None:
            updated_config["version_base_name"] = entry.version_base_name

        return updated_config if updated_config else None
