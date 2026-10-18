"""Shared result aggregation for processing output records."""

import collections
import logging
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, Optional

from agent_actions.errors import AgentActionsError, mark_every_record_failed
from agent_actions.errors import terminal_failure as build_terminal_failure
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    ExhaustedRecordEvent,
    ResultCollectedEvent,
    ResultCollectionCompleteEvent,
    ResultCollectionStartedEvent,
)
from agent_actions.processing.disposition_gate import CARRY_FORWARD_REASON
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.reasons import (
    CONSUMED_INTO_OUTPUT,
    GUARD_FILTER,
    GUARD_PREFILTER_SKIP,
    GUARD_SKIP,
    PARSE_ERROR,
    RETRY_EXHAUSTED,
    SUCCESS,
    UNPROCESSED,
)
from agent_actions.record.state import CASCADE_BLOCKING_VALUES, RecordState
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
from agent_actions.utils import deep_json
from agent_actions.utils.schema_echo import is_schema_echo

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)

# What a reset keeps and the gate carries a record from the stored file by. A reset keeps
# FILTERED too, but a filtered record has no row to carry, and the guard filters it again
# above the gate.
_CARRIED_FROM_THE_STORED_FILE = frozenset({DISPOSITION_SUCCESS, DISPOSITION_PASSTHROUGH})


def _stamp(record: dict[str, Any], state: RecordState, action_name: str, reason: str) -> None:
    """Stamp lifecycle state on a record entering output.

    Records arrive ACTIVE (after downstream reset) or CASCADE_BLOCKING.
    ACTIVE → any settled is legal. CASCADE_BLOCKING → CASCADE_SKIPPED
    is legal (cascade propagation). A record whose latest entry is this action's
    failure already says so: preparation stamps it before the record is collected.
    It gets the state, which a tombstone built from a context-map entry does not
    carry, and no second history entry.
    """
    history = record.get("_state_history")
    last = history[-1] if isinstance(history, list) and history else None
    if (
        state == RecordState.FAILED
        and isinstance(last, dict)
        and last.get("action") == action_name
        and last.get("to") == state.value
    ):
        record["_state"] = state.value
        return
    RecordEnvelope.transition(record, state, action_name, reason)


def _spent_its_retries(result: ProcessingResult) -> bool:
    """Whether the retry loop gave up on *result*.

    A record the provider answered with a per-record error keeps its FAILED
    status so that error survives into the output, so status alone would miss
    exactly the case the policy exists for. Both run modes set ``succeeded``
    False only once the attempts are spent.
    """
    if result.status == ProcessingStatus.EXHAUSTED:
        return True
    retry = result.recovery_metadata.retry if result.recovery_metadata else None
    return result.status == ProcessingStatus.FAILED and retry is not None and not retry.succeeded


def _get_retry_attempts(result: ProcessingResult) -> str | int:
    """Extract retry attempt count from a result's recovery metadata.

    Returns the integer attempt count if available, otherwise ``"unknown"``.
    """
    if result.recovery_metadata and result.recovery_metadata.retry:
        return result.recovery_metadata.retry.attempts
    if result.recovery_metadata and result.recovery_metadata.expectations:
        return result.recovery_metadata.expectations.attempts
    return "unknown"


def _holds_answer(rows: list[dict[str, Any]]) -> bool:
    """Whether a carried row stands as an answer: not failed, exhausted or skipped."""
    return any(
        row.get("_state") not in CASCADE_BLOCKING_VALUES
        and row.get("_state") != RecordState.GUARD_SKIPPED.value
        for row in rows
    )


def _short_guid(source_guid: object) -> str:
    """First segment of a guid — enough to correlate, short enough to read."""
    text = str(source_guid) if source_guid else "unknown"
    return text.split("-", 1)[0]


@dataclass
class CollectionStats:
    """Counts from result collection — returned alongside output records."""

    success: int = 0
    failed: int = 0
    skipped: int = 0
    filtered: int = 0
    exhausted: int = 0
    deferred: int = 0
    unprocessed: int = 0
    carry_forward: int = 0
    # Of the carried records, those holding an answer: the action stands on them as
    # it does on a success this pass produced.
    carried_success: int = 0
    # Why the failures failed, in encounter order. Not a count, so it is
    # excluded from the total below.
    causes: tuple[str, ...] = ()

    @property
    def only_guard_outcomes(self) -> bool:
        """True when every collected record was guard-filtered or skipped.

        A guard skip is collected UNPROCESSED, so it is not among them; a SKIPPED
        result is an empty answer ``on_empty: skip`` kept.

        Uses ``dataclasses.fields()`` so that adding a new status count
        automatically makes this return False until the new field is
        accounted for — no manual update needed.
        """
        # Filtered on the value, not the annotation: under `from __future__
        # import annotations` a field's type is the string "int", and matching
        # on it silently selects nothing.
        total: int = sum(
            value for f in fields(self) if isinstance(value := getattr(self, f.name), int)
        )
        return bool((self.skipped + self.filtered) == total)

    def terminal_failure(
        self,
        action_name: str,
        data: list,
        output: list,
        storage_backend: Optional["StorageBackend"] = None,
    ) -> RuntimeError | None:
        """The RuntimeError to raise if all active records failed, else None.

        Handles two cases:

        1. **only_guard_outcomes** with no output — write a node-level
           SKIPPED disposition so the executor can cascade-skip downstream.
           Skipped records keep a tombstone in ``output``, so ``not output``
           prevents cascade-blocking when one exists. This runs per input
           file, so the executor takes the row as the action's skip only
           while the action holds no record.
        2. **zero successes** among active (non-unprocessed) input records
           with at least one failure — return ``RuntimeError`` for the
           circuit breaker.  Unprocessed records (cascade-quarantined or
           guard-skipped) are excluded from the denominator so
           pass-through-only actions don't erroneously trip the breaker.

        Returned rather than raised so a caller can write the file first where
        leaving it unwritten would leave rows a reset took back
        (``stored_answers_stand``).
        """
        if data and self.only_guard_outcomes and not output:
            write_node_level_disposition(
                storage_backend,
                action_name,
                DISPOSITION_SKIPPED,
                "All records filtered — no output produced",
            )
            return None

        active_input_count = len(data) - self.unprocessed - self.carry_forward
        if (
            active_input_count > 0
            and self.success + self.carried_success == 0
            and (self.failed + self.exhausted) > 0
        ):
            tally = (
                f"produced 0 successful records — "
                f"all {active_input_count} active input item(s) failed or exhausted "
                f"({self.failed} failed, {self.exhausted} exhausted)"
            )
            # The cause leads: every view that renders this truncates, so a
            # cause appended after the tally is the part that gets cut.
            # The cause leads and the action follows it. Leading, because every
            # view that renders this truncates — `agac dispositions` at 60
            # characters — so a trailing cause is the part that gets cut.
            # Always naming the action, because only some paths reach a caller
            # that re-adds it, and an unnamed failure is worse than a repeated
            # name.
            cause = self.dominant_cause
            named = f"Action '{action_name}' {tally}"
            # Every record was reached: the loop re-raises anything that stops it partway.
            failure = build_terminal_failure(f"{cause} — {named}" if cause else named)
            mark_every_record_failed(failure)
            return failure
        return None

    @property
    def dominant_cause(self) -> str:
        """The most common failure reason, or empty when none was recorded."""
        reasons = [c for c in self.causes if c]
        if not reasons:
            return ""
        return collections.Counter(reasons).most_common(1)[0][0]


def _build_failed_tombstone(
    agent_name: str,
    source_guid: str | None,
    input_record: dict[str, Any] | None,
    error: str | None,
) -> dict[str, Any]:
    """Build a tombstone record for a FAILED processing result.

    The tombstone preserves lineage fields (source_guid, root_target_id,
    content from upstream) so downstream actions see the record and can
    cascade-skip it.  This closes the "vanishing record" gap where FAILED
    records previously disappeared from the output stream.
    """
    from agent_actions.processing.record_helpers import build_tombstone

    tombstone = build_tombstone(
        agent_name,
        input_record,
        error or "processing_error",
        source_guid=source_guid,
    )
    _stamp(tombstone, RecordState.FAILED, agent_name, error or "processing_error")
    return tombstone


def _data_has_parse_error(data: list[dict[str, Any]]) -> bool:
    """Check if any data item contains a ``_parse_error`` from the LLM provider.

    The error dict produced by ``JSONResponseMixin`` flows through the transform
    pipeline and lands inside ``content.{action_namespace}._parse_error``.
    """
    for item in data:
        content = item.get("content")
        if isinstance(content, dict):
            for ns_value in content.values():
                if isinstance(ns_value, dict) and "_parse_error" in ns_value:
                    return True
        # Check top-level (raw shape before transform)
        if "_parse_error" in item:
            return True
    return False


def _schema_echoes(data: list[dict[str, Any]], action_name: str) -> set[str]:
    """Records whose row the store refuses as a schema echo, recording them failed."""
    return {
        guid
        for row in data
        if isinstance(row, dict)
        and isinstance(content := row.get("content"), dict)
        and is_schema_echo(content.get(action_name))
        and (guid := row.get("source_guid"))
    }


def _serialize_snapshot(source: dict[str, Any] | None) -> str | None:
    """Serialize a source snapshot dict to JSON for disposition storage.

    Returns None if source is missing, not a dict, or not serializable.
    Truncation to 10KB is handled downstream by sqlite_backend.set_disposition().
    """
    # Empty dict ({}) is treated as absent — reconciler returns {} for missing
    # records, and an empty snapshot has no debugging value.
    if not source or not isinstance(source, dict):
        return None
    try:
        return deep_json.dumps(source, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        logger.debug("Could not serialize input snapshot: %s", type(source).__name__, exc_info=True)
        return None


def _per_item_dispositions(
    pending: list[DispositionRow],
    action_name: str,
    data: list[dict[str, Any]],
    disposition: str,
    reason: str | None = None,
    input_snapshot: str | None = None,
    detail: str | None = None,
) -> int:
    """Write per-item dispositions when the result-level source_guid is None.

    FILE-mode results bundle multiple records into one ProcessingResult with
    source_guid=None.  Individual data items carry their own source_guid.

    Returns the count of items that had a usable source_guid.
    """
    written = 0
    for item in data:
        item_guid = item.get("source_guid")
        if item_guid:
            pending.append(
                (action_name, item_guid, disposition, reason, None, input_snapshot, detail)
            )
            written += 1
    if not written and data:
        logger.warning(
            "[%s] %d data item(s) but none carry source_guid — "
            "dispositions not written (risk of reprocessing on next run)",
            action_name,
            len(data),
        )
    return written


def _safe_set_disposition(
    backend: "StorageBackend",
    action_name: str,
    record_id: str,
    disposition: str,
    **kwargs: Any,
) -> bool:
    """Write a disposition record — log ERROR on failure, do not crash pipeline.

    Returns whether it was stored.
    """
    try:
        backend.set_disposition(action_name, record_id, disposition, **kwargs)
    except Exception:
        logger.exception(
            "Failed to write disposition action=%s record=%s disp=%s — "
            "disposition may diverge from _state until next run",
            action_name,
            record_id,
            disposition,
        )
        return False
    return True


def write_dispositions(
    storage_backend: Optional["StorageBackend"],
    rows: list[DispositionRow],
    action_name: str,
) -> bool:
    """Write *rows* in one transaction — log on failure, do not crash pipeline.

    Returns False only when the store refused them, so none of them is stored.
    """
    if not storage_backend or not rows:
        return True
    try:
        storage_backend.set_dispositions_batch(rows)
    except Exception:
        logger.exception(
            "Failed to batch-write %d dispositions for %s",
            len(rows),
            action_name,
        )
        return False
    return True


def write_node_level_disposition(
    storage_backend: Optional["StorageBackend"],
    action_name: str,
    disposition: str,
    reason: str,
) -> None:
    """Write a node-level disposition for an entire action.

    Used when all records in an action were skipped or passthroughed,
    so there is no per-record output to disposition.
    """
    if storage_backend is None:
        return
    _safe_set_disposition(
        storage_backend, action_name, NODE_LEVEL_RECORD_ID, disposition, reason=reason
    )


def collect_results_from_processing_results(
    results: list[ProcessingResult],
    action_name: str,
    *,
    storage_backend: Optional["StorageBackend"] = None,
    agent_config: dict[str, Any] | None = None,
    context: ProcessingContext | None = None,
) -> tuple[list[dict[str, Any]], CollectionStats]:
    """Shared collect logic for both online and batch retrieve paths.

    Flattens ProcessingResult entries into output records, stamps lifecycle
    state on each, writes dispositions to storage, and fires telemetry events.

    Args:
        results: ProcessingResult objects to collect (enriched).
        action_name: Name of the action being processed.
        storage_backend: Optional storage for disposition writes.
        agent_config: Agent configuration (used for exhausted-raise check
            and guard metadata in completion events). Pass ``None`` when
            calling from batch retrieve — exhausted-raise is not applicable
            and guard metadata is absent.

    Returns:
        Tuple of (output_records, stats). Stats contain counts by status.

    Raises:
        AgentActionsError: If on_exhausted=raise and records exhausted retries,
            unless *context* asks for it to be deferred — batch writes its output
            once at the end, so it parks the error and raises after the write.
    """
    effective_config: dict[str, Any] = agent_config if agent_config is not None else {}

    fire_event(
        ResultCollectionStartedEvent(
            action_name=action_name,
            total_results=len(results),
        )
    )

    if agent_config is not None:
        exhaustion = ResultCollector._handle_exhausted_policy(
            results, effective_config, action_name, storage_backend
        )
        if exhaustion is not None:
            if context is not None and context.defer_exhaustion:
                context.pending_exhaustion = exhaustion
            else:
                raise exhaustion

    output: list[dict[str, Any]] = []
    stats: collections.Counter[str] = collections.Counter()
    causes: list[str] = []
    pending_dispositions: list[DispositionRow] = []
    echoed: set[str] = set()
    guard_skipped_count = 0
    carried_rows = 0

    for idx, result in enumerate(results):
        status = result.status
        status_key = status.value
        stats[status_key] += 1

        if status == ProcessingStatus.SUCCESS:
            data = result.data or []

            if result.skip_reason == CARRY_FORWARD_REASON:
                if data:
                    output.extend(data)
                    carried_rows += len(data)
                stats[status_key] -= 1
                stats["carry_forward"] += 1
                if _holds_answer(data):
                    stats["carried_success"] += 1
                continue

            # Detect parse-error records masquerading as SUCCESS.
            # The LLM provider returns {"_parse_error": ...} on JSON
            # parse failure, which flows through as SUCCESS data.
            # The repair loop has already had its chance (it runs during
            # invocation, before result collection).
            rows = data
            if data and _data_has_parse_error(data):
                # A bundled FILE result holds one row per record, so only the
                # rows that hold the error fail; a keyed result is one record.
                if result.source_guid is None:
                    broken = [d for d in data if _data_has_parse_error([d])]
                    data = [d for d in data if not _data_has_parse_error([d])]
                else:
                    broken, data = data, []
                for d in broken:
                    _stamp(d, RecordState.FAILED, action_name, PARSE_ERROR)
                stats["failed"] += len(broken) if result.source_guid is None else 1
                logger.warning(
                    "[%s] SUCCESS result source_guid=%s contains _parse_error in %d row(s) "
                    "— dispositioned as FAILED",
                    action_name,
                    result.source_guid,
                    len(broken),
                )
                fire_event(
                    ResultCollectedEvent(
                        action_name=action_name,
                        result_index=idx,
                        status="failed",
                    )
                )
                if storage_backend and result.source_guid:
                    pending_dispositions.append(
                        (
                            action_name,
                            result.source_guid,
                            DISPOSITION_FAILED,
                            PARSE_ERROR,
                            None,
                            None,
                            None,
                        )
                    )
                elif storage_backend:
                    _per_item_dispositions(
                        pending_dispositions,
                        action_name,
                        broken,
                        DISPOSITION_FAILED,
                        reason=PARSE_ERROR,
                    )
                if not data:
                    result.status = ProcessingStatus.FAILED
                    stats[status_key] -= 1
                    output.extend(rows)
                    continue

            if data:
                for d in data:
                    _stamp(d, RecordState.PROCESSED, action_name, SUCCESS)
                output.extend(rows)
                echoed |= _schema_echoes(data, action_name)
            logger.debug(
                "Collected SUCCESS result source_guid=%s count=%d",
                result.source_guid,
                len(data),
            )
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="success",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_SUCCESS,
                        None,
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None and data:
                _per_item_dispositions(
                    pending_dispositions,
                    action_name,
                    data,
                    DISPOSITION_SUCCESS,
                )
            if storage_backend:
                for guid in result.collapse_contributor_guids:
                    pending_dispositions.append(
                        (
                            action_name,
                            guid,
                            DISPOSITION_SUCCESS,
                            CONSUMED_INTO_OUTPUT,
                            None,
                            None,
                            None,
                        )
                    )

        elif status == ProcessingStatus.SKIPPED:
            data = result.data or []
            if data:
                for d in data:
                    _stamp(
                        d,
                        RecordState.GUARD_SKIPPED,
                        action_name,
                        result.skip_reason or GUARD_SKIP,
                    )
                output.extend(data)
            logger.debug(
                "Collected SKIPPED result source_guid=%s count=%d",
                result.source_guid,
                len(data),
            )
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="skipped",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_PASSTHROUGH,
                        result.skip_reason or GUARD_SKIP,
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None and data:
                _per_item_dispositions(
                    pending_dispositions,
                    action_name,
                    data,
                    DISPOSITION_PASSTHROUGH,
                    reason=result.skip_reason or GUARD_SKIP,
                )

        elif status == ProcessingStatus.EXHAUSTED:
            data = result.data or []
            if data:
                for d in data:
                    _stamp(
                        d,
                        RecordState.EXHAUSTED,
                        action_name,
                        d.get("_tombstone_reason") or RETRY_EXHAUSTED,
                    )
                output.extend(data)
            attempts = _get_retry_attempts(result)
            logger.debug(
                "Collected EXHAUSTED result source_guid=%s attempts=%s",
                result.source_guid,
                attempts,
            )
            fire_event(
                ExhaustedRecordEvent(
                    action_name=action_name,
                    record_index=idx,
                    source_guid=result.source_guid or "",
                    reason=f"exhausted_after_{attempts}_attempts",
                )
            )
            if storage_backend and result.source_guid:
                input_snapshot_str = _serialize_snapshot(
                    result.source_snapshot or result.input_record
                )
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_EXHAUSTED,
                        f"exhausted_after_{attempts}_attempts",
                        None,
                        input_snapshot_str,
                        result.error,
                    )
                )
            elif storage_backend and result.source_guid is None and data:
                input_snapshot_str = _serialize_snapshot(
                    result.source_snapshot or result.input_record
                )
                _per_item_dispositions(
                    pending_dispositions,
                    action_name,
                    data,
                    DISPOSITION_EXHAUSTED,
                    reason=f"exhausted_after_{attempts}_attempts",
                    input_snapshot=input_snapshot_str,
                    detail=result.error,
                )

        elif status == ProcessingStatus.FAILED:
            # The cause leads: `agac dispositions` truncates a reason at 60
            # characters, and this is the line both online and batch runs get.
            logger.error(
                "[%s] %s (record %s)",
                action_name,
                result.error,
                _short_guid(result.source_guid),
            )
            causes.append(str(result.error) if result.error else "")

            if result.data:
                # Batch FAILED results carry their own data (error items or
                # tombstones from build_tombstone).  Preserve them as-is and
                # stamp lifecycle state.
                for d in result.data:
                    _stamp(d, RecordState.FAILED, action_name, result.error or "processing_error")
                output.extend(result.data)
            else:
                # Online FAILED results have data=[].  Build a tombstone so
                # downstream actions see this record and can cascade-skip it
                # (record-level error isolation).
                tombstone = _build_failed_tombstone(
                    action_name, result.source_guid, result.input_record, result.error
                )
                output.append(tombstone)

            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="failed",
                )
            )
            if storage_backend and result.source_guid:
                input_snapshot_str = _serialize_snapshot(
                    result.source_snapshot or result.input_record
                )
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_FAILED,
                        result.error or "processing_error",
                        None,
                        input_snapshot_str,
                        result.error,
                    )
                )
            elif storage_backend and result.source_guid is None:
                failed_items = result.data or []
                if failed_items:
                    input_snapshot_str = _serialize_snapshot(
                        result.source_snapshot or result.input_record
                    )
                    _per_item_dispositions(
                        pending_dispositions,
                        action_name,
                        failed_items,
                        DISPOSITION_FAILED,
                        reason=result.error or "processing_error",
                        input_snapshot=input_snapshot_str,
                        detail=result.error,
                    )
                else:
                    logger.warning(
                        "[%s] FAILED result has no source_guid and no data — "
                        "disposition not written (risk of reprocessing on next run)",
                        action_name,
                    )

        elif status == ProcessingStatus.FILTERED:
            logger.debug("Collected FILTERED result source_guid=%s", result.source_guid)
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="filtered",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_FILTERED,
                        result.skip_reason or GUARD_FILTER,
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None:
                filtered_data = result.data or []
                if filtered_data:
                    _per_item_dispositions(
                        pending_dispositions,
                        action_name,
                        filtered_data,
                        DISPOSITION_FILTERED,
                        reason=result.skip_reason or GUARD_FILTER,
                    )
                else:
                    logger.warning(
                        "[%s] FILTERED result has no source_guid and no data — "
                        "disposition not written (risk of reprocessing on next run)",
                        action_name,
                    )

        elif status == ProcessingStatus.UNPROCESSED:
            data = result.data or []

            if result.skip_reason == CARRY_FORWARD_REASON:
                if data:
                    output.extend(data)
                    carried_rows += len(data)
                stats[status_key] -= 1
                stats["carry_forward"] += 1
                if _holds_answer(data):
                    stats["carried_success"] += 1
                continue

            if data:
                reason = result.skip_reason or UNPROCESSED
                # FILE prefilter uses UNPROCESSED for ordering (FM13) but is a guard decision
                state = (
                    RecordState.GUARD_SKIPPED
                    if reason in (GUARD_PREFILTER_SKIP, GUARD_SKIP, GUARD_FILTER)
                    else RecordState.CASCADE_SKIPPED
                )
                if state == RecordState.GUARD_SKIPPED:
                    guard_skipped_count += len(data)
                for d in data:
                    _stamp(d, state, action_name, reason)
                output.extend(data)  # Preserve in output for lineage
            logger.debug(
                "Collected UNPROCESSED result source_guid=%s count=%d",
                result.source_guid,
                len(data),
            )
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="unprocessed",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_UNPROCESSED,
                        result.skip_reason or UNPROCESSED,
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None and data:
                _per_item_dispositions(
                    pending_dispositions,
                    action_name,
                    data,
                    DISPOSITION_UNPROCESSED,
                    reason=result.skip_reason or UNPROCESSED,
                )

        elif status == ProcessingStatus.DEFERRED:
            task_id = result.task_id or ""
            logger.info(
                "Collected DEFERRED result source_guid=%s task_id=%s",
                result.source_guid,
                task_id,
            )
            fire_event(
                ResultCollectedEvent(
                    action_name=action_name,
                    result_index=idx,
                    status="deferred",
                )
            )
            if storage_backend and result.source_guid:
                pending_dispositions.append(
                    (
                        action_name,
                        result.source_guid,
                        DISPOSITION_DEFERRED,
                        f"batch_queued:task_id={task_id}",
                        None,
                        None,
                        None,
                    )
                )
            elif storage_backend and result.source_guid is None:
                logger.warning(
                    "[%s] DEFERRED result has no source_guid — "
                    "disposition not written (risk of reprocessing on next run)",
                    action_name,
                )

        else:
            logger.debug("Unhandled result status=%s", status)  # type: ignore[unreachable]

    if context is not None and context.defer_kept_dispositions:
        # They vouch for rows of a file not stored yet; the caller writes them once it is.
        context.kept_dispositions.extend(
            row
            for row in pending_dispositions
            if row[2] in _CARRIED_FROM_THE_STORED_FILE
            # The store records a schema echo failed as it writes the row, and a SUCCESS
            # written after would replace that.
            and row[1] not in echoed
        )
        pending_dispositions = [
            row for row in pending_dispositions if row[2] not in _CARRIED_FROM_THE_STORED_FILE
        ]
    if not write_dispositions(storage_backend, pending_dispositions, action_name):
        if context is not None:
            context.dispositions_not_stored.update(row[1] for row in pending_dispositions)

    guard_config = effective_config.get("guard", {})
    guard_condition = guard_config.get("clause", "") if isinstance(guard_config, dict) else ""
    guard_on_false = guard_config.get("behavior", "") if isinstance(guard_config, dict) else ""

    fire_event(
        ResultCollectionCompleteEvent(
            action_name=action_name,
            total_success=stats["success"],
            total_skipped=stats["skipped"],
            total_filtered=stats["filtered"],
            total_failed=stats["failed"],
            total_exhausted=stats["exhausted"],
            total_unprocessed=stats["unprocessed"],
            total_guard_skipped=guard_skipped_count,
            total_deferred=stats["deferred"],
            guard_condition=guard_condition,
            guard_on_false=guard_on_false,
            target_relative_path=(context.target_relative_path or "") if context else "",
        )
    )

    total_input = len(results)
    if stats["filtered"] > 0 and stats["filtered"] == total_input and total_input > 0:
        logger.warning(
            "[%s] All %d records filtered by guard (%s). None of them reaches downstream actions.",
            action_name,
            total_input,
            guard_condition or "unknown condition",
        )

    tombstone_count = stats["skipped"] + stats["exhausted"] + stats["unprocessed"]
    if tombstone_count > 0:
        logger.info(
            "[%s] %d/%d records are tombstones (skipped=%d, exhausted=%d, unprocessed=%d)",
            action_name,
            tombstone_count,
            len(results),
            stats["skipped"],
            stats["exhausted"],
            stats["unprocessed"],
        )

    if storage_backend is not None:
        storage_backend.credit_rows_collected(action_name, len(output) - carried_rows)

    return output, CollectionStats(
        causes=tuple(causes),
        success=stats["success"],
        failed=stats["failed"],
        skipped=stats["skipped"],
        filtered=stats["filtered"],
        exhausted=stats["exhausted"],
        deferred=stats["deferred"],
        unprocessed=stats["unprocessed"],
        carry_forward=stats["carry_forward"],
        carried_success=stats["carried_success"],
    )


class ResultCollector:
    """Collect output records from processing results."""

    @staticmethod
    def collect_results(
        results: list[ProcessingResult],
        agent_config: dict[str, Any],
        agent_name: str,
        *,
        is_first_stage: bool,
        storage_backend: Optional["StorageBackend"] = None,
        context: ProcessingContext | None = None,
    ) -> tuple[list[dict[str, Any]], CollectionStats]:
        """Flatten ProcessingResult entries into output records.

        Delegates to ``collect_results_from_processing_results()`` — the
        shared helper used by both online and batch retrieve paths.

        Returns:
            Tuple of (output_records, stats). Stats contain counts by status.

        Raises:
            AgentActionsError: If on_exhausted=raise and records exhausted retries,
            unless the caller asked for it to be deferred.
        """
        return collect_results_from_processing_results(
            results,
            agent_name,
            storage_backend=storage_backend,
            agent_config=agent_config,
            context=context,
        )

    @staticmethod
    def _handle_exhausted_policy(
        results: list[ProcessingResult],
        agent_config: dict[str, Any],
        agent_name: str,
        storage_backend: Optional["StorageBackend"],
    ) -> Exception | None:
        """Handle exhausted retries according to on_exhausted policy.

        For return_last (default): logs at INFO. For raise: writes EXHAUSTED
        dispositions and hands back the error, leaving the caller to decide when
        to throw it — batch has not written its output file yet.
        """
        exhausted_results = [
            r
            for r in results
            if _spent_its_retries(r)
            # Expectations exhaustion resolved its own on_exhausted policy in
            # the service; the retry config's policy does not apply to it.
            and not (r.recovery_metadata and r.recovery_metadata.expectations)
        ]
        if not exhausted_results:
            return None

        retry_config = agent_config.get("retry") or {}
        on_exhausted = retry_config.get("on_exhausted") or "return_last"

        if on_exhausted != "raise":
            logger.info(
                "[%s] %d records exhausted retries (on_exhausted=%s)",
                agent_name,
                len(exhausted_results),
                on_exhausted,
            )
            return None

        logger.warning(
            "[%s] %d records exhausted retries — raising (on_exhausted=raise)",
            agent_name,
            len(exhausted_results),
        )

        if storage_backend:
            for er in exhausted_results:
                if er.source_guid:
                    input_snapshot_str = _serialize_snapshot(er.source_snapshot or er.input_record)
                    _safe_set_disposition(
                        storage_backend,
                        agent_name,
                        er.source_guid,
                        DISPOSITION_EXHAUSTED,
                        reason=f"exhausted_after_{_get_retry_attempts(er)}_attempts",
                        input_snapshot=input_snapshot_str,
                        detail=er.error,
                    )
                else:
                    er_data = er.data or []
                    if er_data:
                        input_snapshot_str = _serialize_snapshot(
                            er.source_snapshot or er.input_record
                        )
                        written = 0
                        for item in er_data:
                            item_guid = item.get("source_guid")
                            if item_guid:
                                _safe_set_disposition(
                                    storage_backend,
                                    agent_name,
                                    item_guid,
                                    DISPOSITION_EXHAUSTED,
                                    reason=f"exhausted_after_{_get_retry_attempts(er)}_attempts",
                                    input_snapshot=input_snapshot_str,
                                    detail=er.error,
                                )
                                written += 1
                        if not written:
                            logger.warning(
                                "[%s] %d exhausted data item(s) but none carry "
                                "source_guid — dispositions not written "
                                "(on_exhausted=raise)",
                                agent_name,
                                len(er_data),
                            )
                    else:
                        logger.warning(
                            "[%s] Exhausted result has no source_guid and no data — "
                            "disposition not written (on_exhausted=raise)",
                            agent_name,
                        )

        first = exhausted_results[0]
        return AgentActionsError(
            f"Retry exhausted for record {first.source_guid} after "
            f"{_get_retry_attempts(first)} attempts (on_exhausted=raise)",
            context={
                "agent_name": agent_name,
                "exhausted_records": len(exhausted_results),
                "on_exhausted": "raise",
            },
        )
