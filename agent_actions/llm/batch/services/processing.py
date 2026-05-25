"""Batch processing service for converting batch results to workflow output."""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.config.types import ActionConfigDict, RunMode
from agent_actions.errors import ProcessingError
from agent_actions.llm.batch.core.batch_constants import (
    BatchStatus,
    OnExhaustedPolicy,
    RecoveryPhase,
    RecoveryType,
)
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import BatchIdentity, BatchJobEntry, RecoveryContext
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
    cleanup_recovery as _cleanup_recovery_impl,
)
from agent_actions.llm.batch.services.processing_recovery import (
    finalize_batch_output as _finalize_batch_output_impl,
)
from agent_actions.llm.batch.services.processing_recovery import (
    process_recovery_batch as _process_recovery_batch_impl,
)
from agent_actions.llm.batch.services.processing_recovery import (
    register_recovery_batch,
)
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.writer import FileWriter
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.result_collector import CollectionStats, _safe_set_disposition
from agent_actions.processing.types import ProcessingContext, RecoveryMetadata
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.storage.backend import DISPOSITION_DEFERRED, DISPOSITION_FAILED
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
        self._enrichment_pipeline = EnrichmentPipeline()
        self._unified_processor = UnifiedProcessor(enrichment_pipeline=self._enrichment_pipeline)

    def process_batch_results(
        self,
        batch_id: str,
        output_directory: str,
        agent_config: dict[str, Any] | None = None,
    ) -> str:
        """Process a single batch by ID with retry/reprompt support.

        Uses the same retry/reprompt logic as the production path
        (process_all_batch_results). If recovery is needed, a recovery
        batch is submitted and ProcessingError is raised — the caller
        must re-invoke after the recovery batch completes.

        Args:
            batch_id: Batch job ID
            output_directory: Output directory path
            agent_config: Agent configuration

        Returns:
            Path to output file

        Raises:
            ProcessingError: If batch not completed, no registry entry,
                recovery is pending, or processing fails
        """
        try:
            manager = self._registry_manager_factory(output_directory)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

            if provider.check_status(batch_id) != BatchStatus.COMPLETED:
                raise ProcessingError("Batch job is not completed", context={"batch_id": batch_id})

            entry = manager.get_batch_job_by_id(batch_id)
            if not entry:
                raise ProcessingError(
                    "No registry entry found for batch",
                    context={"batch_id": batch_id},
                )

            file_name = entry.file_name or "default"

            output_file = self._process_single_batch_file(
                batch_id=batch_id,
                file_name=file_name,
                entry=entry,
                output_directory=output_directory,
                agent_config=agent_config,
                manager=manager,
                action_name=self._action_name,
            )

            if output_file is None:
                raise ProcessingError(
                    "Batch recovery submitted — re-invoke after recovery batch completes",
                    context={"batch_id": batch_id},
                )

            return output_file
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

            if not self._is_batch_ready_for_processing(batch_id, output_directory, agent_config):
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
            except RuntimeError:
                raise
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
                self._fail_abandoned_records(
                    file_name=file_name,
                    output_directory=output_directory,
                    action_name=effective_action_name,
                    error=e,
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

    def _is_batch_ready_for_processing(
        self,
        batch_id: str,
        output_directory: str,
        agent_config: dict[str, Any] | None = None,
    ) -> bool:
        """Check if batch is ready for processing (completed status).

        Args:
            batch_id: The batch job ID to check
            output_directory: Directory containing batch registry
            agent_config: Optional agent config for API key resolution

        Returns:
            True if batch status is COMPLETED, False otherwise
        """
        try:
            manager = self._registry_manager_factory(output_directory)
            provider = self._client_resolver.get_for_batch_id(
                batch_id, manager, output_directory, agent_config=agent_config
            )
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
        """Write batch output file, merging any carry-forward records first."""
        effective_action = action_name or self._action_name
        main_output = self._merge_carry_forward(effective_action, main_output, output_directory)

        if self._storage_backend is None:
            ensure_directory_exists(output_file, is_file=True)
        FileWriter(
            str(output_file),
            storage_backend=self._storage_backend,
            action_name=effective_action,
            output_directory=output_directory,
        ).write_target(main_output)

    def _merge_carry_forward(
        self,
        action_name: str | None,
        batch_output: list[dict[str, Any]],
        output_directory: str,
    ) -> list[dict[str, Any]]:
        """Merge carry-forward records from prior output into batch results."""
        from agent_actions.llm.batch.services.submission import (
            BATCH_CARRY_FORWARD_FILENAME,
        )

        carry_path = Path(output_directory) / "batch" / BATCH_CARRY_FORWARD_FILENAME
        try:
            carry_data = json.loads(carry_path.read_text())
            carry_guids = set(carry_data.get("guids", []))
        except FileNotFoundError:
            return batch_output
        except (json.JSONDecodeError, KeyError):
            logger.warning("Malformed .batch_carry_forward.json — skipping merge")
            return batch_output

        if not carry_guids or not self._storage_backend or not action_name:
            return batch_output

        from agent_actions.processing.disposition_gate import build_carry_forward

        carry_records: list[dict[str, Any]] = []
        for rel_path in self._storage_backend.list_target_files(action_name):
            found, _missing = build_carry_forward(
                carry_guids, action_name, rel_path, self._storage_backend
            )
            carry_records.extend(found)

        batch_guids = {r.get("source_guid") for r in batch_output if r.get("source_guid")}
        overlap = carry_guids & batch_guids
        if overlap:
            logger.warning(
                "Carry-forward/batch overlap for %d records — deduplicating",
                len(overlap),
            )
            carry_records = [r for r in carry_records if r.get("source_guid") not in overlap]

        if carry_records:
            logger.info(
                "Merging %d carry-forward records into batch output for %s",
                len(carry_records),
                action_name,
            )

        try:
            carry_path.unlink()
        except OSError:
            logger.debug("Failed to clean up %s", carry_path)

        return batch_output + carry_records

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
        provider = self._client_resolver.get_for_batch_id(
            batch_id, manager, output_directory, agent_config=agent_config
        )

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
            missing_ids = BatchResultReconciler.find_missing_ids(context_map, batch_results)

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
                    retry_batch_id, _record_count = submission
                    register_recovery_batch(
                        manager,
                        submission,
                        file_name,
                        entry.provider,
                        RecoveryType.RETRY,
                        1,
                    )

                    record_failure_counts = {rid: 1 for rid in missing_ids}
                    state = RecoveryState(
                        phase=RecoveryPhase.RETRY,
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
                        state.on_exhausted = OnExhaustedPolicy(reprompt_parsed.on_exhausted)

                    RecoveryStateManager.save(output_directory, file_name, state)
                    logger.info(
                        "Async retry submitted for %s: %d missing records, batch %s",
                        file_name,
                        len(missing_ids),
                        retry_batch_id,
                    )
                    return None  # Recovery pending

        # Build context objects for recovery functions
        context = RecoveryContext(
            service=self,
            manager=manager,
            provider=provider,
            agent_config=agent_config or {},
            output_directory=output_directory,
            action_name=action_name,
            start_time=start_time,
        )
        identity = BatchIdentity(
            batch_id=batch_id,
            file_name=file_name,
            entry=entry,
        )

        # Do NOT load recovery state here. The original batch path processes
        # from scratch — any existing recovery_state file is stale (left by a
        # crashed run). Passing it would poison the reprompt check with a stale
        # reprompt_attempt counter, causing it to think attempts are exhausted.
        # Stale files are cleaned up in _finalize_batch_output.
        should_continue = self._check_and_submit_reprompt(
            context=context,
            identity=identity,
            batch_results=batch_results,
            context_map=context_map,
            recovery_state=None,
        )
        if not should_continue:
            return None  # Reprompt submitted, processing paused

        return self._finalize_batch_output(
            context=context,
            identity=identity,
            batch_results=batch_results,
            context_map=context_map,
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
        context: RecoveryContext,
        identity: BatchIdentity,
        batch_results: list[BatchResult],
        context_map: dict[str, Any],
        recovery_state: RecoveryState | None = None,
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    ) -> bool:
        """Check if reprompt is needed and submit async batch if so.

        Delegates to processing_recovery.check_and_submit_reprompt.
        """
        return _check_and_submit_reprompt_impl(
            context,
            identity,
            batch_results=batch_results,
            context_map=context_map,
            recovery_state=recovery_state,
            exhausted_recovery=exhausted_recovery,
        )

    def _finalize_batch_output(
        self,
        context: RecoveryContext,
        identity: BatchIdentity,
        batch_results: list[BatchResult],
        context_map: dict[str, Any],
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    ) -> str:
        """Finalize batch processing: convert, write output, fire events, cleanup.

        Delegates to processing_recovery.finalize_batch_output then cleanup_recovery.
        Also cleans up any stale recovery state left by a crashed previous run.
        """
        # Clean up stale recovery state (e.g. from a crashed previous run).
        # The recovery path already does this in _finalize_and_cleanup, but the
        # original batch path goes through this method instead and must also clean up.
        RecoveryStateManager.delete(context.output_directory, identity.file_name)
        output_path = _finalize_batch_output_impl(
            context,
            identity,
            batch_results=batch_results,
            context_map=context_map,
            exhausted_recovery=exhausted_recovery,
        )
        _cleanup_recovery_impl(context, identity)
        return output_path

    def _clear_deferred_dispositions(
        self, items: list[dict[str, Any]], action_name: str | None = None
    ) -> None:
        """Clear DEFERRED dispositions for batch records entering output.

        Batch records receive DEFERRED dispositions at submit time under
        the per-action name.  After retrieve, the shared collector writes
        final dispositions (SUCCESS, FAILED, etc.), but DEFERRED entries
        remain unless explicitly cleared.

        Args:
            action_name: Per-action name used when DEFERRED was written.
                Falls back to self._action_name (workflow name) if not given.
        """
        effective_name = action_name or self._action_name
        if not self._storage_backend or not effective_name:
            return
        for item in items:
            source_guid = item.get("source_guid")
            if source_guid:
                self._try_clear_deferred(effective_name, source_guid)

    def _write_filtered_dispositions(self, context_map: dict[str, Any], action_name: str) -> None:
        """Write FILTERED dispositions for records excluded from output.

        FILTERED records are removed from the output stream by the reconciler
        (they never reach write_record_dispositions). This method ensures they
        still receive DISPOSITION_FILTERED to match online ResultCollector parity.
        """
        if not self._storage_backend or not context_map:
            return
        from agent_actions.llm.batch.core.batch_constants import FilterStatus
        from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
        from agent_actions.record.reasons import GUARD_FILTER
        from agent_actions.storage.backend import DISPOSITION_FILTERED

        for _custom_id, entry in context_map.items():
            if BatchContextMetadata.get_filter_status(entry) != FilterStatus.FILTERED:
                continue
            source_guid = entry.get("source_guid")
            if not source_guid:
                continue
            reason = BatchContextMetadata.get_skip_reason(entry) or GUARD_FILTER
            self._try_clear_deferred(action_name, source_guid)
            try:
                self._storage_backend.set_disposition(
                    action_name, source_guid, DISPOSITION_FILTERED, reason=reason
                )
            except Exception:
                logger.debug(
                    "Failed to write FILTERED disposition for %s", source_guid, exc_info=True
                )

    def _try_clear_deferred(self, action_name: str, record_id: str) -> None:
        """Clear a DEFERRED disposition for one record. Swallows errors."""
        if not self._storage_backend:
            return
        from agent_actions.storage.backend import DISPOSITION_DEFERRED

        try:
            self._storage_backend.clear_disposition(
                action_name,
                disposition=DISPOSITION_DEFERRED,
                record_id=record_id,
            )
        except Exception:
            logger.debug(
                "Could not clear DEFERRED disposition for %s (may not exist)",
                record_id,
                exc_info=True,
            )

    def _update_prompt_trace_responses(self, items: list[dict[str, Any]], action_name: str) -> None:
        """Update prompt traces with batch responses for SUCCESS records only.

        Only records with _state=processed represent actual LLM responses.
        Tombstones (exhausted, failed, skipped) must not pollute prompt traces.
        """
        if not self._storage_backend:
            return
        from agent_actions.record.state import RecordState

        try:
            for item in items:
                if item.get("_state") != RecordState.PROCESSED.value:
                    continue
                target_id = item.get("target_id")
                if not target_id:
                    continue
                content = item.get("content")
                if content is None:
                    continue
                # Extract only the action's output namespace — matches online prompt trace shape
                action_output = (
                    content.get(action_name, content) if isinstance(content, dict) else content
                )
                response_text = json.dumps(action_output, ensure_ascii=False, default=str)
                self._storage_backend.update_prompt_trace_response(
                    action_name=action_name,
                    record_id=target_id,
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

    def _fail_abandoned_records(
        self,
        file_name: str,
        output_directory: str,
        action_name: str | None,
        error: Exception,
    ) -> None:
        """Write FAILED dispositions for INCLUDED records in a batch file that threw an exception.

        Without this, records remain stuck with stale DEFERRED dispositions —
        the retry command won't find them and subsequent reruns won't know they failed.
        """
        if not self._storage_backend or not action_name:
            return

        try:
            context_map = self._context_manager.load_batch_context_map(
                output_directory, file_name or "default"
            )
        except Exception:
            logger.warning(
                "Could not load context_map for failed batch %s (action=%s) — "
                "records may remain with stale DEFERRED dispositions",
                file_name,
                action_name,
                exc_info=True,
            )
            return

        reason = f"batch_processing_exception: {str(error)[:500]}"
        failed_count = 0
        for _custom_id, record in context_map.items():
            if not BatchContextMetadata.is_included(record):
                continue
            source_guid = record.get("source_guid")
            if not source_guid:
                continue

            try:
                self._storage_backend.clear_disposition(
                    action_name,
                    disposition=DISPOSITION_DEFERRED,
                    record_id=source_guid,
                )
            except Exception:
                logger.debug(
                    "Could not clear DEFERRED disposition for %s (may not exist)",
                    source_guid,
                    exc_info=True,
                )

            _safe_set_disposition(
                self._storage_backend,
                action_name,
                source_guid,
                DISPOSITION_FAILED,
                reason=reason,
            )
            failed_count += 1

        if failed_count:
            logger.warning(
                "Wrote FAILED disposition for %d abandoned records in batch %s (action=%s): %s",
                failed_count,
                file_name,
                action_name,
                str(error)[:200],
            )

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
    ) -> tuple[list[dict[str, Any]], CollectionStats]:
        """Convert batch results to workflow format via UnifiedProcessor.

        Routes batch results through the shared enrich → collect pipeline
        (same path online uses), eliminating the duplicate inline loop.

        Args:
            batch_results: Raw batch results
            context_map: Context map for processing
            output_directory: Output directory path
            agent_config: Agent configuration
            exhausted_recovery: Per-record recovery metadata for exhausted records

        Returns:
            Tuple of (output_records, CollectionStats).
        """
        results = self._result_processor.process(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
            exhausted_recovery=exhausted_recovery,
        )

        effective_config = agent_config or {}
        ctx = ProcessingContext(
            agent_config=cast(ActionConfigDict, effective_config),
            agent_name=effective_config.get("action_name", "batch"),
            mode=RunMode.BATCH,
            storage_backend=self._storage_backend,
        )

        return self._unified_processor.enrich_and_collect(results, ctx)

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
