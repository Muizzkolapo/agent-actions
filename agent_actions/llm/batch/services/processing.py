"""Batch processing service for converting batch results to workflow output."""

import logging
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
from agent_actions.errors import ProcessingError, is_action_fatal
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.expectations.service import ExpectationConfigurationError
from agent_actions.llm.batch.core.batch_constants import (
    BatchStatus,
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
    batch_output_name,
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
from agent_actions.llm.batch.services.collect import (
    collect_batch_rows,
    halt_survives_failure,
    write_batch_file,
)
from agent_actions.llm.batch.services.processing_recovery import (
    check_and_submit_repair as _check_and_submit_repair_impl,
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
    raise_pending_exhaustion as _raise_pending_exhaustion_impl,
)
from agent_actions.llm.batch.services.processing_recovery import (
    register_recovery_batch,
)
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.batch.services.retry_serialization import (
    serialize_results,
)
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.writer import target_relative_path
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.result_collector import CollectionStats, _safe_set_disposition
from agent_actions.processing.types import RecoveryMetadata
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.storage.backend import DISPOSITION_DEFERRED, DISPOSITION_FAILED

logger = logging.getLogger(__name__)


def _is_dead_retry(entry: BatchJobEntry) -> bool:
    """A retry recovery the provider terminally failed.

    It holds the live recovery state, and the failure path continues it: the
    spent attempt is counted and the next one submitted, or exhaustion applies.
    Repair recoveries are excluded — their in-flight records' last responses
    are not recoverable from state, so their dead batches keep the
    processed-from-scratch path.
    """
    return entry.recovery_type == RecoveryType.RETRY and entry.status in (
        BatchStatus.FAILED,
        BatchStatus.CANCELLED,
    )


def _superseded_entries(jobs: dict[str, BatchJobEntry]) -> set[str]:
    """Registry keys that are no longer the live job for their parent.

    COMPLETED (readable now) and in-flight (readable later) recoveries
    supersede outright. A terminally failed retry recovery also supersedes —
    its next step is counting the spent attempt, then resubmission or
    exhaustion — but only when the parent has no readable recovery: a dead
    attempt must not outrank a usable sibling's actual results. Anything else
    (a dead recovery batch, an unrecognised status) supersedes nothing, because
    nothing would process it and a parent skipped for a recovery that never
    produces wedges the action.

    Among live recoveries the newest wins, ranked by registration time, not by
    attempt or phase: a store written before registration started replacing
    its predecessor can hold a retry registered *after* a repair and
    numbered below it, which either of those orderings gets backwards.
    """
    live: dict[str, tuple[str, int, str]] = {}
    dead_retries: dict[str, tuple[str, int, str]] = {}
    for name, entry in jobs.items():
        parent = entry.parent_file_name
        if not parent:
            continue
        rank = (entry.timestamp or "", entry.recovery_attempt or 0, name)
        if entry.status == BatchStatus.COMPLETED or entry.is_in_flight:
            if parent not in live or rank > live[parent]:
                live[parent] = rank
        elif _is_dead_retry(entry):
            if parent not in dead_retries or rank > dead_retries[parent]:
                dead_retries[parent] = rank

    for parent, rank in dead_retries.items():
        live.setdefault(parent, rank)

    superseded = set(live)
    superseded.update(
        name
        for name, entry in jobs.items()
        if entry.parent_file_name in live and name != live[entry.parent_file_name][2]
    )
    return superseded


@dataclass
class CollectPass:
    """The files a collect pass wrote, and the finished ones it could not read.

    A file left unread still owes its results, so the action waits for it as for a batch
    still out: completed, the action is not run again and nothing reads that batch.
    """

    written: list[str] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)


class BatchProcessingService:
    """Service for processing batch job results.

    Handles result retrieval, conversion, and output file generation.
    Delegates retry logic to BatchRetryService.
    """

    def __init__(
        self,
        client_resolver: BatchClientResolver,
        context_manager: BatchContextManager,
        result_processor: BatchResultStrategy,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
        action_indices: dict[str, int] | None = None,
        dependency_configs: dict[str, dict] | None = None,
        storage_backend: Optional["StorageBackend"] = None,
        workflow_name: str | None = None,
    ):
        """Initialize processing service with dependencies.

        Args:
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            result_processor: Processor for batch results
            registry_manager_factory: Factory function to create registry managers
            action_indices: Dict mapping agent names to node indices (for recovery)
            dependency_configs: Dict mapping dependency names to configs (for recovery)
            storage_backend: Optional storage backend for database persistence
            workflow_name: Workflow-level name (fallback when per-action name unavailable)
        """
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._result_processor = result_processor
        self._registry_manager_factory = registry_manager_factory
        self._action_indices = action_indices or {}
        self._dependency_configs = dependency_configs or {}
        self._storage_backend = storage_backend
        self._workflow_name = workflow_name
        self._retry_service = BatchRetryService(
            action_indices=self._action_indices,
            dependency_configs=self._dependency_configs,
            storage_backend=self._storage_backend,
        )
        self._enrichment_pipeline = EnrichmentPipeline()
        self._unified_processor = UnifiedProcessor(enrichment_pipeline=self._enrichment_pipeline)

    def _resolve_action_name(self, override: str | None = None) -> str:
        """Resolve the effective action name from an override or the workflow-level fallback.

        Raises:
            ProcessingError: If neither override nor workflow_name is set.
        """
        resolved = override or self._workflow_name
        if not resolved:
            raise ProcessingError(
                "action_name or workflow_name required for batch processing",
                context={},
            )
        return resolved

    def process_batch_results(
        self,
        batch_id: str,
        output_directory: str,
        agent_config: dict[str, Any] | None = None,
        action_name: str | None = None,
    ) -> str:
        """Process a single batch by ID with retry and repair support.

        Uses the same retry and repair logic as the production path
        (process_all_batch_results). If recovery is needed, a recovery
        batch is submitted and ProcessingError is raised — the caller
        must re-invoke after the recovery batch completes.

        Args:
            batch_id: Batch job ID
            output_directory: Output directory path
            agent_config: Agent configuration
            action_name: Per-action name for registry lookup

        Returns:
            Path to output file

        Raises:
            ProcessingError: If batch not completed, no registry entry,
                recovery is pending, or processing fails
        """
        effective_name = self._resolve_action_name(action_name)
        assert self._storage_backend is not None, "storage_backend required for batch processing"
        try:
            manager = self._registry_manager_factory(effective_name)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)

            if provider.check_status(batch_id) != BatchStatus.COMPLETED:
                raise ProcessingError("Batch job is not completed", context={"batch_id": batch_id})

            entry = manager.get_batch_job_by_id(batch_id)
            if not entry:
                raise ProcessingError(
                    "No registry entry found for batch",
                    context={"batch_id": batch_id},
                )

            if not entry.file_name:
                raise ProcessingError(
                    "Registry entry missing file_name — cannot determine batch context key",
                    context={"batch_id": batch_id},
                )
            file_name = entry.file_name

            if file_name in _superseded_entries(manager.get_all_jobs()):
                raise ProcessingError(
                    "A later recovery batch supersedes this one — process that instead",
                    context={"batch_id": batch_id, "file_name": file_name},
                )

            output_file = self._process_single_batch_file(
                batch_id=batch_id,
                file_name=file_name,
                entry=entry,
                output_directory=output_directory,
                agent_config=agent_config,
                manager=manager,
                action_name=effective_name,
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
    ) -> CollectPass:
        """Process the completed batch jobs whose results are still owed.

        Recovery entries are processed in their own right; the parent they
        superseded is skipped instead, and so is an entry already collected.
        A finished entry the provider cannot be asked about, or reports running again,
        is left unread, as is the parent a recovery dropped in the pass hands back; one
        it reports ended any other way, or does not know, has its records marked failed.
        Tolerates writing nothing when recovery batches are pending
        (in_progress), a collected entry was skipped, or an entry was left unread.

        Args:
            output_directory: Output directory path
            agent_config: Agent configuration
            action_name: Override action_name for storage backend writes (uses self._workflow_name if not provided)

        Returns:
            The output file paths written, and the files left unread

        Raises:
            ProcessingError: If no registry found, or no files processed while none
                was skipped as collected or left unread and no recovery is pending
        """
        effective_action_name = self._resolve_action_name(action_name)
        manager = self._registry_manager_factory(effective_action_name)
        all_jobs = manager.get_all_jobs()
        if not all_jobs:
            raise ProcessingError(
                "No batch registry found", context={"output_directory": output_directory}
            )

        processed_files = []
        unread: list[str] = []
        # Spent entries stay COMPLETED, so nothing else stops the loop re-reading
        # one: that restarts recovery at attempt 1, or finalizes on stale results
        # and deletes the live attempt. Stores written before this can hold them.
        # Decided once, before the loop mutates anything: a parent whose recovery
        # finalizes mid-pass has its child removed by the cleanup, and re-reading
        # the registry would then call that parent live again and re-run the
        # original batch. Superseded once, skipped for the whole pass.
        superseded = _superseded_entries(all_jobs)
        collected_before = False
        for file_name in all_jobs:
            if file_name in superseded:
                logger.info("Skipping %s: a later recovery attempt supersedes it", file_name)
                continue

            # The loop body replaces and deletes entries, so a snapshot batch_id
            # can already be stale — and an unregistered id has no client, which
            # ends the run rather than this batch.
            entry = manager.get_batch_job(file_name)
            if entry is None:
                logger.info("Skipping %s: no longer in the registry", file_name)
                continue

            batch_id = entry.batch_id
            if not batch_id:
                continue

            # Its results are already written, and a later run may have written over
            # them: read again, a spent batch puts back rows for records that have left.
            # Before the poll, so a spent batch costs no provider call and cannot fail
            # the pass. An entry from before the stamp existed reads as uncollected.
            if entry.collected_at is not None:
                collected_before = True
                logger.info("Skipping %s: collected at %s", file_name, entry.collected_at)
                continue

            # A dead retry recovery is processed without a readiness poll: its
            # provider status is terminal, and the failure path needs no results.
            if not _is_dead_retry(entry):
                status = self._provider_status(
                    batch_id, output_directory, agent_config, action_name=effective_action_name
                )
                if status != BatchStatus.COMPLETED:
                    if entry.status != BatchStatus.COMPLETED:
                        continue
                    # Its last poll said finished, so its results are owed all the same.
                    if status is None or status in BatchStatus.in_flight_states():
                        logger.warning(
                            "Could not read %s (batch %s) in this pass: %s. The action "
                            "waits for it",
                            file_name,
                            batch_id,
                            "the provider could not be asked about it"
                            if status is None
                            else f"the provider reports it {status}",
                        )
                        unread.append(file_name)
                        continue
                    # Ended without results, or unknown to the provider: no later pass
                    # can read it, so waiting would hold the action for good.
                    logger.warning(
                        "Could not read %s (batch %s): the provider reports it %s, not "
                        "completed. Its records are marked failed for `agac retry`",
                        file_name,
                        batch_id,
                        status,
                    )
                    self._fail_abandoned_records(
                        # A recovery round is sent from its parent's context map.
                        file_name=entry.parent_file_name or file_name,
                        output_directory=output_directory,
                        action_name=effective_action_name,
                        error=ProcessingError(
                            f"batch {batch_id} is {status} at the provider, not completed"
                        ),
                    )
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
            except (RuntimeError, ExpectationConfigurationError, EmptyOutputError):
                # An unresolvable `expect:` block is not this file's problem:
                # every remaining file carries the same action config and fails
                # the same way, so continuing would finish the run reporting
                # success with each of them missing from the output. A plain
                # ConfigurationError is per record — a malformed lifecycle state
                # — and stays below, costing only its own file. The halt `on_empty:
                # error` asks for is raised once its file is written: taken as that
                # file's failure, its records are marked failed over what they hold.
                raise
            except Exception as e:
                # Declared where it was raised: a store that failed to write the file,
                # or the halt `on_exhausted: raise` asks for. Taken as this file's
                # failure, the action completes over what the file held before.
                if is_action_fatal(e):
                    raise
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

        # A recovery dropped in this pass hands back the parent it superseded, which
        # the loop has already skipped. One that finalized stamped its parent collected.
        for name in sorted(superseded - _superseded_entries(manager.get_all_jobs())):
            parent = manager.get_batch_job(name)
            if parent is not None and parent.awaits_collection:
                logger.warning(
                    "Could not read %s in this pass: it was skipped for a recovery since "
                    "dropped. The action waits for it",
                    name,
                )
                unread.append(name)

        # A file already collected counts as one this pass did not fail, as a replay of
        # it that succeeded did. One left unread is waited for, not failed.
        if not processed_files and not collected_before and not unread:
            # Check if recovery batches are pending — not an error
            stats = manager.get_registry_stats()
            if stats.in_progress > 0:
                return CollectPass()
            raise ProcessingError(
                "No batch results were successfully processed",
                context={"output_directory": output_directory},
            )
        return CollectPass(written=processed_files, unread=unread)

    def _provider_status(
        self,
        batch_id: str,
        output_directory: str,
        agent_config: dict[str, Any] | None = None,
        action_name: str | None = None,
    ) -> str | None:
        """The batch's status at the provider, or None when the provider cannot be asked."""
        resolved = self._resolve_action_name(action_name)
        try:
            manager = self._registry_manager_factory(resolved)
            provider = self._client_resolver.get_for_batch_id(
                batch_id, manager, output_directory, agent_config=agent_config
            )
            return provider.check_status(batch_id)
        except (OSError, ConnectionError) as e:
            logger.warning("Transient error checking batch status for %s: %s", batch_id, e)
            return None

    def _determine_output_path(
        self, output_directory: str, file_name: str | None, batch_id: str
    ) -> Path:
        """Determine the output file path for batch results.

        Args:
            output_directory: Base output directory
            file_name: Original file name
            batch_id: Batch job ID for fallback naming

        Returns:
            Path object for the output file
        """
        if file_name:
            return Path(output_directory) / batch_output_name(file_name)
        return Path(output_directory) / f"{batch_id}_processed_output.json"

    def _write_batch_output(
        self,
        output_file: Path,
        main_output: list[dict[str, Any]],
        output_directory: str,
        action_name: str | None = None,
        *,
        batch_inputs: Collection[str] = (),
        filtered: Collection[str] = (),
    ) -> None:
        """Write the batch output file through ``write_batch_file``."""
        write_batch_file(
            self._storage_backend,
            self._resolve_action_name(action_name),
            main_output,
            output_root=output_directory,
            stored_name=target_relative_path(output_file, output_directory),
            batch_inputs=batch_inputs,
            filtered=filtered,
        )

    def _merge_carry_forward(
        self,
        action_name: str | None,
        batch_output: list[dict[str, Any]],
        relative_path: str,
        *,
        batch_inputs: Collection[str] = (),
    ) -> list[dict[str, Any]]:
        """Hand back every stored row this batch did not answer for.

        A *stored* row's disposition does not decide whether it comes back: `failed`
        is not terminal, and a batch narrowed to one record would drop the rest. What
        the run *produced* is read the other way round — only a settled row answers for
        an input, and for the inputs it names rather than the identity it carries.

        *batch_inputs* is the input before narrowing: once the action above mints its
        own identities, the rows alone cannot say which producers still exist.
        """
        if not self._storage_backend or not action_name:
            return batch_output

        from agent_actions.processing.disposition_gate import with_stored_rows_not_reproduced

        return with_stored_rows_not_reproduced(
            batch_output,
            action_name,
            relative_path,
            self._storage_backend,
            batch_inputs=batch_inputs,
        )

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
        3. Validate results → submit async repair if needed
        4. If neither needed → write output

        Returns:
            Output file path if processing is complete, None if recovery batch was submitted
        """
        start_time = time.time()

        effective_name = self._resolve_action_name(action_name)
        context_map = self._context_manager.load_batch_context_map(
            self._storage_backend,  # type: ignore[arg-type]
            effective_name,  # type: ignore[arg-type]
            file_name,
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
                        accumulated_results=serialize_results(batch_results),
                    )
                    RecoveryStateManager.save(
                        self._storage_backend,  # type: ignore[arg-type]
                        effective_name,  # type: ignore[arg-type]
                        file_name,
                        state,
                    )
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
            action_name=effective_name,
            start_time=start_time,
        )
        identity = BatchIdentity(
            batch_id=batch_id,
            file_name=file_name,
            entry=entry,
        )

        # Do NOT load recovery state here. The original batch path processes
        # from scratch — any existing recovery_state file is stale (left by a
        # crashed run), and a stale repair counter would read as exhausted.
        # Stale files are cleaned up in _finalize_batch_output.
        # Same wrapper the recovery handlers get: a halt parked below must not be
        # lost to an unrelated failure on the way to the finaliser.
        with halt_survives_failure(context):
            if not _check_and_submit_repair_impl(
                context=context,
                identity=identity,
                batch_results=batch_results,
                context_map=context_map,
                recovery_state=None,
            ):
                _raise_pending_exhaustion_impl(context)
                return None  # Repair round submitted, processing paused

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
        """Process a recovery batch (retry or repair).

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
        RecoveryStateManager.delete(
            self._storage_backend,  # type: ignore[arg-type]
            self._resolve_action_name(context.action_name),
            identity.file_name,
        )
        output_path = _finalize_batch_output_impl(
            context,
            identity,
            batch_results=batch_results,
            context_map=context_map,
            exhausted_recovery=exhausted_recovery,
        )
        _cleanup_recovery_impl(context, identity)
        _raise_pending_exhaustion_impl(context)
        return output_path

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
                self._storage_backend,  # type: ignore[arg-type]
                action_name,  # type: ignore[arg-type]
                file_name,
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
        action_name: str | None = None,
    ) -> tuple[list[dict[str, Any]], CollectionStats, Exception | None]:
        """Collect the file's rows and dispositions through ``collect_batch_rows``.

        Returns (rows, stats, halt); the halt is raised by the caller once the file is
        written. *action_name* defaults to the config's.
        """
        return collect_batch_rows(
            self._storage_backend,
            action_name or self._resolve_action_name((agent_config or {}).get("action_name")),
            agent_config,
            context_map,
            batch_results,
            output_directory=output_directory,
            exhausted_recovery=exhausted_recovery,
            result_processor=self._result_processor,
            unified_processor=self._unified_processor,
        )

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
