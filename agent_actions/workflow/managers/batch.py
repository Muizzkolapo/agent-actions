"""Batch job lifecycle management for status checking and result processing."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from rich.console import Console

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError, ProcessingError
from agent_actions.llm.batch.core.batch_constants import RecoveryType
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    BatchErrorEvent,
    BatchPassthroughEvent,
    BatchProcessingCompleteEvent,
    BatchResultsProcessedEvent,
    BatchStatusEvent,
)
from agent_actions.storage.backend import (
    DISPOSITION_DEFERRED,
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_FILTERED,
    DISPOSITION_PASSTHROUGH,
    DISPOSITION_SKIPPED,
    DISPOSITION_SUCCESS,
    DISPOSITION_UNPROCESSED,
    NODE_LEVEL_RECORD_ID,
    DispositionRow,
)

# Dispositions that indicate a record reached a terminal outcome.
# A DEFERRED record with a terminal sibling is NOT orphaned.
_TERMINAL_DISPOSITIONS = frozenset(
    {
        DISPOSITION_SUCCESS,
        DISPOSITION_FAILED,
        DISPOSITION_FILTERED,
        DISPOSITION_EXHAUSTED,
        DISPOSITION_SKIPPED,
    }
)

if TYPE_CHECKING:
    from agent_actions.llm.batch.services.processing import CollectPass
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class BatchLifecycleManager:
    """Manages batch job lifecycle and result processing."""

    def __init__(
        self,
        job_manager,
        processing_service,
        console: Console | None = None,
        storage_backend: Optional["StorageBackend"] = None,
    ):
        """Initialize batch lifecycle manager.

        Args:
            job_manager: BatchJobManager for registry status and completion checks.
            processing_service: BatchProcessingService for result processing.
            console: Optional Rich console for output.
            storage_backend: Required storage backend for disposition tracking.

        Raises:
            ConfigurationError: If storage_backend is None
        """
        if storage_backend is None:
            raise ConfigurationError(
                "BatchLifecycleManager requires a storage_backend. "
                "Disposition tracking is not optional.",
                context={"component": "BatchLifecycleManager"},
            )
        self.job_manager = job_manager
        self.processing_service = processing_service
        self.console = console or Console()
        self.storage_backend = storage_backend

    def handle_batch_agent(
        self,
        agent_name: str,
        output_directory: str,
        agent_config: dict[str, Any] | None = None,
        workflow_metadata: dict[str, Any] | None = None,
    ) -> tuple[str | None, str]:
        """Check batch status and process results.

        Returns:
            (output_folder or None, batch_status) where status is
            'completed', 'in_progress', or 'failed'.
        """
        registry_status = self.job_manager.get_registry_status(agent_name)

        if registry_status == "completed":
            fire_event(BatchProcessingCompleteEvent(action_name=agent_name))
            collected = self._process_batch_results(
                output_directory, agent_config, agent_name, workflow_metadata
            )
            # Re-check — processing may have submitted recovery batches
            new_status = self.job_manager.get_registry_status(agent_name)
            if new_status != "completed" or collected.unread:
                return (None, "in_progress")
            fire_event(BatchResultsProcessedEvent(action_name=agent_name))
            return (output_directory, "completed")

        if registry_status in ["in_progress", "partial_failed"]:
            if self.job_manager.are_all_jobs_completed(agent_name, output_directory, agent_config):
                fire_event(BatchProcessingCompleteEvent(action_name=agent_name))
                collected = self._process_batch_results(
                    output_directory, agent_config, agent_name, workflow_metadata
                )
                # Re-check — processing may have submitted recovery batches
                new_status = self.job_manager.get_registry_status(agent_name)
                if new_status != "completed" or collected.unread:
                    return (None, "in_progress")
                fire_event(BatchResultsProcessedEvent(action_name=agent_name))
                return (output_directory, "completed")
            return (None, "in_progress")

        if registry_status == "cancelled":
            fire_event(
                BatchStatusEvent(
                    action_name=agent_name,
                    status_message=f"All batch jobs cancelled for {agent_name}",
                    status_type="warning",
                )
            )
            return (None, "failed")

        if registry_status == "no_batches":
            has_passthrough = self.storage_backend.has_disposition(
                agent_name, DISPOSITION_PASSTHROUGH
            )
            if has_passthrough:
                fire_event(BatchPassthroughEvent(action_name=agent_name))
                return (output_directory, "completed")
            fire_event(
                BatchStatusEvent(
                    action_name=agent_name,
                    status_message=f"No batch jobs found for {agent_name}",
                    status_type="warning",
                )
            )
            return (None, "failed")

        return (None, "failed")

    def _process_batch_results(
        self,
        output_directory: str,
        agent_config: dict[str, Any] | None,
        agent_name: str,
        workflow_metadata: dict[str, Any] | None = None,
    ) -> "CollectPass":
        """Process all completed batch job results.

        Raises:
            ProcessingError: If result processing fails.
        """
        try:
            collected: CollectPass = self.processing_service.process_all_batch_results(
                output_directory,
                agent_config=agent_config,
                action_name=agent_name,
                workflow_metadata=workflow_metadata,
            )
            if not collected.written:
                logger.info(
                    "Nothing collected for %s in this pass — recovery batches may be "
                    "pending, a finished file could not be read, or every file was "
                    "collected before",
                    agent_name,
                )

        except ProcessingError:
            fire_event(
                BatchErrorEvent(
                    action_name=agent_name,
                    error_message="Could not process batch results",
                    error_type="ProcessingError",
                )
            )
            raise
        except Exception as e:
            fire_event(
                BatchErrorEvent(
                    action_name=agent_name,
                    error_message=f"Could not process batch results: {str(e)}",
                    error_type=type(e).__name__,
                )
            )
            raise

        # The records of a file left unread are waited for, not orphaned.
        if not collected.unread:
            self._warn_orphaned_deferred(agent_name)
        return collected

    def _warn_orphaned_deferred(self, agent_name: str) -> None:
        """Log a warning if genuinely orphaned DEFERRED records remain.

        A record is orphaned when it has a DEFERRED disposition (set at batch
        submit) but never received a terminal disposition (SUCCESS, FAILED,
        FILTERED, etc.).  Records that have both DEFERRED and a terminal
        sibling are NOT orphans — they simply have a stale DEFERRED row that
        will be cleared.  This is diagnostic only and never raises.
        """
        try:
            # Fast path: query only DEFERRED (indexed). If none remain, done.
            deferred_rows = self.storage_backend.get_disposition(
                agent_name, disposition=DISPOSITION_DEFERRED, snapshots=False
            )
            if not deferred_rows:
                return

            deferred_ids = {r["record_id"] for r in deferred_rows if r.get("record_id")}
            if not deferred_ids:
                return

            # Slow path: DEFERRED rows exist — check for terminal siblings.
            terminal_ids: set[str] = set()
            for disp in _TERMINAL_DISPOSITIONS:
                for r in self.storage_backend.get_disposition(
                    agent_name, disposition=disp, snapshots=False
                ):
                    rid = r.get("record_id")
                    if rid and rid in deferred_ids:
                        terminal_ids.add(str(rid))
                if not (deferred_ids - terminal_ids):
                    return

            orphan_ids = self._report_records_awaiting_recovery(
                agent_name, deferred_ids - terminal_ids
            )
            if orphan_ids:
                sample = sorted(orphan_ids)[:10]
                logger.warning(
                    "[%s] %d record(s) still in DEFERRED state after batch completion "
                    "— possible orphans: %s. The next run or retry writes the outcome "
                    "of each one whose row is stored",
                    agent_name,
                    len(orphan_ids),
                    sample,
                )
        except Exception:
            logger.debug(
                "Could not check for orphaned DEFERRED dispositions for %s",
                agent_name,
                exc_info=True,
            )

    def _report_records_awaiting_recovery(self, agent_name: str, record_ids: set[str]) -> set[str]:
        """Report the records a pending recovery batch holds; return the rest.

        A record a retry or repair batch was sent for waits on it, and is reported
        with the failure recorded for its last attempt rather than as an orphan.
        """
        from agent_actions.llm.batch.infrastructure.recovery_state import (
            AwaitingRecovery,
            records_awaiting_recovery,
        )

        try:
            awaiting = records_awaiting_recovery(self.storage_backend, agent_name)
        except Exception:
            logger.debug("Could not read the recovery batches of %s", agent_name, exc_info=True)
            return record_ids

        groups: dict[AwaitingRecovery, list[str]] = {}
        for record_id in record_ids & awaiting.keys():
            groups.setdefault(awaiting[record_id], []).append(record_id)

        for where, ids in sorted(
            groups.items(), key=lambda item: (str(item[0].recovery_type), item[0].failure or "")
        ):
            attempt, max_attempts, failure = where.attempt, where.max_attempts, where.failure
            sample = sorted(ids)[:10]
            if where.recovery_type == RecoveryType.REPAIR:
                logger.info(
                    "[%s] %d record(s) wait on repair round %d of %d: %s",
                    agent_name,
                    len(ids),
                    attempt,
                    max_attempts,
                    sample,
                )
            elif failure:
                logger.warning(
                    "[%s] %d record(s) wait on retry attempt %d of %d after their last "
                    "attempt failed: %s: %s",
                    agent_name,
                    len(ids),
                    attempt,
                    max_attempts,
                    failure[:500],
                    sample,
                )
            else:
                logger.warning(
                    "[%s] %d record(s) wait on retry attempt %d of %d: the provider "
                    "returned no result for them: %s",
                    agent_name,
                    len(ids),
                    attempt,
                    max_attempts,
                    sample,
                )
        return record_ids - awaiting.keys()

    def check_batch_submission(
        self,
        agent_name: str,
        agent_idx: int,
        agent_io_path: Path,
        configured_run_mode: RunMode | None = None,
    ) -> str | None:
        """Return 'batch_submitted', 'passthrough', 'no_batches', or None."""
        # YAML config is authoritative — stale batch files do not override
        if configured_run_mode == RunMode.ONLINE:
            return None

        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        registry_manager = BatchRegistryManager(self.storage_backend, agent_name)
        # Uncollected, not merely present: a spent entry is left in the registry
        # after its results are written, and pausing on one sends the run back
        # for a batch that has nothing left to give.
        if registry_manager.has_uncollected_jobs():
            return "batch_submitted"

        # Check passthrough disposition
        if self.storage_backend.has_disposition(agent_name, DISPOSITION_PASSTHROUGH):
            return "passthrough"

        node_output_dir = agent_io_path / "target" / agent_name
        if node_output_dir.exists():
            # Output dir exists but no batch registry or passthrough
            return "no_batches"
        return None


_QUEUED_PREFIX = "batch_queued:batch_id="


def lost_dispositions(storage_backend: "StorageBackend", action_name: str) -> list[DispositionRow]:
    """The disposition each record of a collected batch lost, read from its stored row.

    The collect pass stores a record's row and then writes its disposition; when the store
    refuses that write, the record keeps the ``deferred`` its submission stamped. Once every
    batch of the action is collected, the row stands for what the lost disposition said.
    Only a ``deferred`` naming a collected batch is answered, and only from a row whose
    state names one outcome; a record with no row, or a row in no settled state, is left
    ``deferred``. One that already holds another disposition only loses the stale mark,
    returned as its ``deferred`` row.
    """
    deferred = [
        row
        for row in storage_backend.get_disposition(
            action_name, disposition=DISPOSITION_DEFERRED, snapshots=False
        )
        if row.get("record_id") and row["record_id"] != NODE_LEVEL_RECORD_ID
    ]
    if not deferred:
        return []

    from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

    jobs = BatchRegistryManager(storage_backend, action_name).get_all_jobs()
    # A batch not yet collected, a recovery round's included, still answers its records.
    if not jobs or any(entry.collected_at is None for entry in jobs.values()):
        return []
    collected = {entry.batch_id for entry in jobs.values() if entry.batch_id}

    held: dict[str, set[str]] = {}
    for row in storage_backend.get_disposition(action_name, snapshots=False):
        held.setdefault(row.get("record_id") or "", set()).add(row.get("disposition") or "")
    rows_of = _stored_rows_by_record(storage_backend, action_name)

    settled: list[DispositionRow] = []
    for row in deferred:
        record_id = row["record_id"]
        reason = row.get("reason") or ""
        if not reason.startswith(_QUEUED_PREFIX) or reason[len(_QUEUED_PREFIX) :] not in collected:
            continue
        if held.get(record_id, set()) - {DISPOSITION_DEFERRED}:
            settled.append((action_name, record_id, DISPOSITION_DEFERRED, None, None, None, None))
            continue
        outcome = _outcome_of(rows_of.get(record_id, []), action_name)
        if outcome is not None:
            disposition, why, detail = outcome
            settled.append((action_name, record_id, disposition, why, None, None, detail))
    return settled


def settle_lost_dispositions(
    storage_backend: "StorageBackend", settled: list[DispositionRow]
) -> None:
    """Write what ``lost_dispositions`` read, then clear each record's ``deferred``."""
    storage_backend.set_dispositions_batch(
        [row for row in settled if row[2] != DISPOSITION_DEFERRED]
    )
    for action_name, record_id, *_ in settled:
        storage_backend.clear_disposition(
            action_name, disposition=DISPOSITION_DEFERRED, record_id=record_id
        )


def _stored_rows_by_record(
    storage_backend: "StorageBackend", action_name: str
) -> dict[str, list[dict[str, Any]]]:
    """Each stored row of *action_name*, under its identity and each input that produced it."""
    rows_of: dict[str, list[dict[str, Any]]] = {}
    for relative_path in storage_backend.list_target_files(action_name):
        try:
            stored = storage_backend.read_target_for_rewrite(action_name, relative_path)
        except FileNotFoundError:
            continue
        for stored_row in stored:
            names = {
                stored_row.get("source_guid"),
                *(stored_row.get("producer_source_guids") or ()),
            }
            for name in names - {None, ""}:
                rows_of.setdefault(str(name), []).append(stored_row)
    return rows_of


def _outcome_of(
    rows: list[dict[str, Any]], action_name: str
) -> tuple[str, str | None, str | None] | None:
    """(disposition, reason, detail) the collect pass wrote for a record holding *rows*.

    A record answered with any row is ``success``, as a split's rows are. Otherwise its
    row's state and the reason this action gave it say what the collect pass wrote; an
    answer kept empty (``on_empty: skip``) is ``passthrough``.
    """
    from agent_actions.record.reasons import EMPTY_OUTPUT, UNPROCESSED
    from agent_actions.record.state import RecordState

    if not rows:
        return None
    states = {row.get("_state") for row in rows}
    if RecordState.PROCESSED.value in states:
        return (DISPOSITION_SUCCESS, None, None)
    if len(states) != 1:
        return None
    (state,) = states
    entry = _last_entry(rows[0], action_name, state)
    reason = entry.get("reason") if entry else None
    detail = entry.get("detail") if entry else None
    if state == RecordState.FAILED.value:
        return (DISPOSITION_FAILED, reason or "processing_error", detail or reason)
    if state == RecordState.EXHAUSTED.value:
        return _exhaustion_of(rows[0], reason) or (DISPOSITION_EXHAUSTED, reason, detail)
    if state == RecordState.GUARD_SKIPPED.value and reason == EMPTY_OUTPUT:
        return (DISPOSITION_PASSTHROUGH, reason, None)
    if state in (RecordState.GUARD_SKIPPED.value, RecordState.CASCADE_SKIPPED.value):
        return (DISPOSITION_UNPROCESSED, reason or UNPROCESSED, None)
    return None


def _exhaustion_of(
    row: dict[str, Any], reason: str | None
) -> tuple[str, str | None, str | None] | None:
    """The EXHAUSTED disposition collection wrote, read from *row*'s recovery metadata.

    None when the row does not hold the attempt count the reason is built from.
    """
    from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
    from agent_actions.processing.types import RecoveryMetadata
    from agent_actions.record.reasons import EXPECTATIONS_EXHAUSTED

    recovery = row.get("_recovery")
    if not isinstance(recovery, dict):
        return None
    try:
        metadata = RecoveryMetadata.from_dict(recovery)
    except (TypeError, KeyError):
        return None
    if metadata.retry is not None:
        attempts = metadata.retry.attempts
    elif metadata.expectations is not None:
        attempts = metadata.expectations.attempts
    else:
        return None
    if reason == EXPECTATIONS_EXHAUSTED and metadata.expectations is not None:
        error, _ = ExhaustedRecordBuilder.expectations_exhaustion(metadata.expectations)
    else:
        error = f"Retry exhausted after {attempts} attempts"
    return (DISPOSITION_EXHAUSTED, f"exhausted_after_{attempts}_attempts", error)


def _last_entry(row: dict[str, Any], action_name: str, state: Any) -> dict[str, Any] | None:
    """The latest history entry in which *action_name* moved *row* to *state*."""
    history = row.get("_state_history")
    if not isinstance(history, list):
        return None
    for entry in reversed(history):
        if isinstance(entry, dict) and entry.get("action") == action_name:
            return entry if entry.get("to") == state else None
    return None
