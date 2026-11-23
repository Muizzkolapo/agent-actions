"""Shared result aggregation for processing output records."""

import collections
import logging
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, Optional

from agent_actions.errors import (
    AgentActionsError,
    DispositionsNotStoredError,
    mark_action_fatal,
    mark_every_record_failed,
)
from agent_actions.errors import terminal_failure as build_terminal_failure
from agent_actions.expectations.report import verdict_of
from agent_actions.llm.providers.tools.builtin import route_case_counts
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    ExhaustedRecordEvent,
    ResultCollectedEvent,
    ResultCollectionCompleteEvent,
    ResultCollectionStartedEvent,
)
from agent_actions.processing.disposition_gate import CARRY_FORWARD_REASON
from agent_actions.processing.run_counts import add_collection
from agent_actions.processing.types import ProcessingContext, ProcessingResult, ProcessingStatus
from agent_actions.record.elsewhere import guard_filter_reason
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.reasons import (
    CONSUMED_INTO_OUTPUT,
    EMPTY_OUTPUT,
    EXPECTATIONS_FAILED,
    GUARD_SKIP_REASONS,
    PARSE_ERROR,
    RETRY_EXHAUSTED,
    SENT_ELSEWHERE,
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
    FAILURE_DISPOSITIONS,
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


_SUB_COUNTS = frozenset({"guard_skipped", "checks_failed", "sent_elsewhere"})


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
    # Sub-counts, not statuses, so also excluded from the total below: the rows a
    # guard skipped (stored as unprocessed) and the records shipped with a failing
    # verdict (stored as success).
    guard_skipped: int = 0
    checks_failed: int = 0
    # Records the guard sent to another branch: filtered here but not this action's,
    # so neither among ``filtered`` nor in the total.
    sent_elsewhere: int = 0
    # A built-in router's rows per case, in the router's order; None for any other action.
    cases: dict[str, int] | None = None

    @property
    def only_guard_outcomes(self) -> bool:
        """True when something was collected and every record was guard-filtered or skipped.

        With nothing collected no guard acted, so it is False.

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
            value
            for f in fields(self)
            if f.name not in _SUB_COUNTS and isinstance(value := getattr(self, f.name), int)
        )
        return total > 0 and (self.skipped + self.filtered) == total

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


def failed_its_checks(row: dict[str, Any], action_name: str) -> bool:
    """Whether *row* shipped carrying its own verdict with ``overall_pass`` false.

    The one test of "this record failed its checks": every mode, kind and granularity
    reaches the collector with the verdict under the action's own namespace. A failed
    ``warn`` or ``info`` rule never sets ``overall_pass`` false, so it does not count.
    """
    verdict = verdict_of(row, action_name)
    return verdict is not None and verdict.get("overall_pass") is False


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
    return _refusal_of(storage_backend, rows, action_name) is None


def _refusal_of(
    storage_backend: Optional["StorageBackend"],
    rows: list[DispositionRow],
    action_name: str,
) -> Exception | None:
    """Write *rows* in one transaction, returning the error the store refused them with."""
    if not storage_backend or not rows:
        return None
    try:
        storage_backend.set_dispositions_batch(rows)
    except Exception as refused:
        logger.exception(
            "Failed to batch-write %d dispositions for %s",
            len(rows),
            action_name,
        )
        return refused
    return None


def failures_not_stored(
    action_name: str, record_ids: list[str], refused: Exception
) -> DispositionsNotStoredError:
    """The error that fails an action whose records' failures the store would not hold.

    Fatal to the action, not to the file: the walk would otherwise carry on past it and
    complete the action with those records holding nothing.
    """
    shown = ", ".join(record_ids[:3]) + (" ..." if len(record_ids) > 3 else "")
    error = DispositionsNotStoredError(
        f"The store refused the failure of {len(record_ids)} record(s) ({shown}): "
        f"{refused}. Unrecorded, `agac retry` could not find them, "
        "so the action is failed; once the store answers, `agac retry` re-runs it.",
        context={"action_name": action_name, "record_ids": record_ids},
        cause=refused,
    )
    mark_action_fatal(error)
    return error


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


@dataclass
class _Collection:
    """What one walk over the results gathers before it is written and reported."""

    action_name: str
    storage_backend: Optional["StorageBackend"]
    output: list[dict[str, Any]] = field(default_factory=list)
    stats: collections.Counter[str] = field(default_factory=collections.Counter)
    causes: list[str] = field(default_factory=list)
    pending: list[DispositionRow] = field(default_factory=list)
    echoed: set[str] = field(default_factory=set)
    guard_skipped: int = 0
    # Records whose rows shipped a failing verdict, and failing rows with no record id.
    failed_guids: set[str] = field(default_factory=set)
    unidentified_failed: int = 0
    carried_rows: int = 0
    routed: list[dict[str, Any]] = field(default_factory=list)

    def collected(self, idx: int, status: str) -> None:
        fire_event(
            ResultCollectedEvent(
                action_name=self.action_name,
                result_index=idx,
                status=status,
            )
        )

    def record(
        self,
        guid: str,
        disposition: str,
        reason: str | None = None,
        input_snapshot: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.pending.append(
            (self.action_name, guid, disposition, reason, None, input_snapshot, detail)
        )

    def record_each(
        self,
        data: list[dict[str, Any]],
        disposition: str,
        reason: str | None = None,
        input_snapshot: str | None = None,
        detail: str | None = None,
    ) -> None:
        _per_item_dispositions(
            self.pending,
            self.action_name,
            data,
            disposition,
            reason=reason,
            input_snapshot=input_snapshot,
            detail=detail,
        )


def _collect_carried(acc: _Collection, data: list[dict[str, Any]], status_key: str) -> None:
    """Count a row the gate carried from the stored file, not one this pass produced."""
    if data:
        acc.output.extend(data)
        acc.carried_rows += len(data)
    acc.stats[status_key] -= 1
    acc.stats["carry_forward"] += 1
    if _holds_answer(data):
        acc.stats["carried_success"] += 1


def _fail_parse_errors(
    acc: _Collection, idx: int, result: ProcessingResult, data: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fail the rows holding a ``_parse_error``, returning the rows that still succeed.

    The LLM provider returns {"_parse_error": ...} on JSON parse failure, which
    flows through as SUCCESS data. The repair loop has already had its chance (it
    runs during invocation, before result collection).
    """
    action_name = acc.action_name
    # A bundled FILE result holds one row per record, so only the
    # rows that hold the error fail; a keyed result is one record.
    if result.source_guid is None:
        broken = [d for d in data if _data_has_parse_error([d])]
        data = [d for d in data if not _data_has_parse_error([d])]
    else:
        broken, data = data, []
    for d in broken:
        _stamp(d, RecordState.FAILED, action_name, PARSE_ERROR)
    acc.stats["failed"] += len(broken) if result.source_guid is None else 1
    logger.warning(
        "[%s] SUCCESS result source_guid=%s contains _parse_error in %d row(s) "
        "— dispositioned as FAILED",
        action_name,
        result.source_guid,
        len(broken),
    )
    acc.collected(idx, "failed")
    if acc.storage_backend and result.source_guid:
        acc.record(result.source_guid, DISPOSITION_FAILED, PARSE_ERROR)
    elif acc.storage_backend:
        acc.record_each(broken, DISPOSITION_FAILED, reason=PARSE_ERROR)
    return data


def _record_success(acc: _Collection, result: ProcessingResult, data: list[dict[str, Any]]) -> None:
    """Note failing verdicts and queue the SUCCESS dispositions of *result*'s rows."""
    action_name = acc.action_name
    if result.source_guid:
        if any(failed_its_checks(d, action_name) for d in data):
            acc.failed_guids.add(result.source_guid)
        if acc.storage_backend:
            acc.record(result.source_guid, DISPOSITION_SUCCESS)
    elif result.source_guid is None and data:
        # A bundled FILE result: each row carries its record's own source_guid.
        for d in data:
            if failed_its_checks(d, action_name):
                if d.get("source_guid"):
                    acc.failed_guids.add(d["source_guid"])
                else:
                    acc.unidentified_failed += 1
        if acc.storage_backend:
            acc.record_each(data, DISPOSITION_SUCCESS)
    if acc.storage_backend:
        for guid in result.collapse_contributor_guids:
            acc.record(guid, DISPOSITION_SUCCESS, CONSUMED_INTO_OUTPUT)


def _collect_success(acc: _Collection, idx: int, result: ProcessingResult, status_key: str) -> None:
    data = result.data or []
    if result.skip_reason == CARRY_FORWARD_REASON:
        _collect_carried(acc, data, status_key)
        return

    rows = data
    if data and _data_has_parse_error(data):
        data = _fail_parse_errors(acc, idx, result, data)
        if not data:
            result.status = ProcessingStatus.FAILED
            acc.stats[status_key] -= 1
            acc.output.extend(rows)
            return

    if data:
        for d in data:
            _stamp(d, RecordState.PROCESSED, acc.action_name, SUCCESS)
        acc.output.extend(rows)
        acc.routed.extend(data)
        acc.echoed |= _schema_echoes(data, acc.action_name)
    logger.debug(
        "Collected SUCCESS result source_guid=%s count=%d",
        result.source_guid,
        len(data),
    )
    acc.collected(idx, "success")
    _record_success(acc, result, data)


def _collect_skipped(acc: _Collection, idx: int, result: ProcessingResult) -> None:
    data = result.data or []
    reason = result.skip_reason or EMPTY_OUTPUT
    if data:
        for d in data:
            _stamp(d, RecordState.GUARD_SKIPPED, acc.action_name, reason)
        acc.output.extend(data)
    logger.debug(
        "Collected SKIPPED result source_guid=%s count=%d",
        result.source_guid,
        len(data),
    )
    acc.collected(idx, "skipped")
    if acc.storage_backend and result.source_guid:
        acc.record(result.source_guid, DISPOSITION_PASSTHROUGH, reason)
    elif acc.storage_backend and result.source_guid is None and data:
        acc.record_each(data, DISPOSITION_PASSTHROUGH, reason=reason)


def _collect_exhausted(acc: _Collection, idx: int, result: ProcessingResult) -> None:
    data = result.data or []
    if data:
        for d in data:
            _stamp(
                d,
                RecordState.EXHAUSTED,
                acc.action_name,
                d.get("_tombstone_reason") or RETRY_EXHAUSTED,
            )
        acc.output.extend(data)
    attempts = _get_retry_attempts(result)
    acc.causes.append(str(result.error) if result.error else "")
    logger.debug(
        "Collected EXHAUSTED result source_guid=%s attempts=%s",
        result.source_guid,
        attempts,
    )
    reason = f"exhausted_after_{attempts}_attempts"
    fire_event(
        ExhaustedRecordEvent(
            action_name=acc.action_name,
            record_index=idx,
            source_guid=result.source_guid or "",
            reason=reason,
        )
    )
    if acc.storage_backend and result.source_guid:
        input_snapshot_str = _serialize_snapshot(result.source_snapshot or result.input_record)
        acc.record(
            result.source_guid, DISPOSITION_EXHAUSTED, reason, input_snapshot_str, result.error
        )
    elif acc.storage_backend and result.source_guid is None and data:
        input_snapshot_str = _serialize_snapshot(result.source_snapshot or result.input_record)
        acc.record_each(
            data,
            DISPOSITION_EXHAUSTED,
            reason=reason,
            input_snapshot=input_snapshot_str,
            detail=result.error,
        )


def _collect_failed(acc: _Collection, idx: int, result: ProcessingResult) -> None:
    action_name = acc.action_name
    reason = result.error or "processing_error"
    # The cause leads: `agac dispositions` truncates a reason at 60
    # characters, and this is the line both online and batch runs get.
    logger.error(
        "[%s] %s (record %s)",
        action_name,
        result.error,
        _short_guid(result.source_guid),
    )
    acc.causes.append(str(result.error) if result.error else "")

    if result.data:
        # Batch FAILED results carry their own data (error items or
        # tombstones from build_tombstone).  Preserve them as-is and
        # stamp lifecycle state.
        for d in result.data:
            _stamp(d, RecordState.FAILED, action_name, reason)
        acc.output.extend(result.data)
    else:
        # Online FAILED results have data=[].  Build a tombstone so
        # downstream actions see this record and can cascade-skip it
        # (record-level error isolation).
        tombstone = _build_failed_tombstone(
            action_name, result.source_guid, result.input_record, result.error
        )
        acc.output.append(tombstone)

    acc.collected(idx, "failed")
    if acc.storage_backend and result.source_guid:
        input_snapshot_str = _serialize_snapshot(result.source_snapshot or result.input_record)
        acc.record(result.source_guid, DISPOSITION_FAILED, reason, input_snapshot_str, result.error)
    elif acc.storage_backend and result.source_guid is None:
        failed_items = result.data or []
        if failed_items:
            input_snapshot_str = _serialize_snapshot(result.source_snapshot or result.input_record)
            acc.record_each(
                failed_items,
                DISPOSITION_FAILED,
                reason=reason,
                input_snapshot=input_snapshot_str,
                detail=result.error,
            )
        else:
            logger.warning(
                "[%s] FAILED result has no source_guid and no data — "
                "disposition not written (risk of reprocessing on next run)",
                action_name,
            )


def _collect_filtered(
    acc: _Collection,
    idx: int,
    result: ProcessingResult,
    status_key: str,
    config: dict[str, Any],
) -> None:
    logger.debug("Collected FILTERED result source_guid=%s", result.source_guid)
    filter_reason = result.skip_reason or guard_filter_reason(config)
    if filter_reason == SENT_ELSEWHERE:
        acc.stats[status_key] -= 1
        acc.stats["sent_elsewhere"] += 1
    acc.collected(idx, "filtered")
    if acc.storage_backend and result.source_guid:
        acc.record(result.source_guid, DISPOSITION_FILTERED, filter_reason)
    elif acc.storage_backend and result.source_guid is None:
        filtered_data = result.data or []
        if filtered_data:
            acc.record_each(filtered_data, DISPOSITION_FILTERED, reason=filter_reason)
        else:
            logger.warning(
                "[%s] FILTERED result has no source_guid and no data — "
                "disposition not written (risk of reprocessing on next run)",
                acc.action_name,
            )


def _collect_unprocessed(
    acc: _Collection, idx: int, result: ProcessingResult, status_key: str
) -> None:
    data = result.data or []
    if result.skip_reason == CARRY_FORWARD_REASON:
        _collect_carried(acc, data, status_key)
        return

    reason = result.skip_reason or UNPROCESSED
    if data:
        # FILE prefilter uses UNPROCESSED for ordering (FM13) but is a guard decision
        state = (
            RecordState.GUARD_SKIPPED
            if reason in GUARD_SKIP_REASONS
            else RecordState.CASCADE_SKIPPED
        )
        if state == RecordState.GUARD_SKIPPED:
            acc.guard_skipped += len(data)
        for d in data:
            _stamp(d, state, acc.action_name, reason)
        acc.output.extend(data)  # Preserve in output for lineage
    logger.debug(
        "Collected UNPROCESSED result source_guid=%s count=%d",
        result.source_guid,
        len(data),
    )
    acc.collected(idx, "unprocessed")
    if acc.storage_backend and result.source_guid:
        acc.record(result.source_guid, DISPOSITION_UNPROCESSED, reason)
    elif acc.storage_backend and result.source_guid is None and data:
        acc.record_each(data, DISPOSITION_UNPROCESSED, reason=reason)


def _collect_deferred(acc: _Collection, idx: int, result: ProcessingResult) -> None:
    task_id = result.task_id or ""
    logger.info(
        "Collected DEFERRED result source_guid=%s task_id=%s",
        result.source_guid,
        task_id,
    )
    acc.collected(idx, "deferred")
    if acc.storage_backend and result.source_guid:
        acc.record(result.source_guid, DISPOSITION_DEFERRED, f"batch_queued:task_id={task_id}")
    elif acc.storage_backend and result.source_guid is None:
        logger.warning(
            "[%s] DEFERRED result has no source_guid — "
            "disposition not written (risk of reprocessing on next run)",
            acc.action_name,
        )


def _write_pending(acc: _Collection, context: ProcessingContext | None) -> None:
    """Write the queued dispositions, or hand the kept ones to *context* to write later."""
    pending = acc.pending
    if acc.failed_guids:
        # Marked once the whole collection is seen: one record's rows can arrive in
        # several results (a resumed expansion), and any failing row fails the record.
        pending = [
            (*row[:3], EXPECTATIONS_FAILED, *row[4:])
            if row[2] == DISPOSITION_SUCCESS and row[3] is None and row[1] in acc.failed_guids
            else row
            for row in pending
        ]
    if context is not None and context.defer_kept_dispositions:
        # They vouch for rows of a file not stored yet; the caller writes them once it is.
        context.kept_dispositions.extend(
            row
            for row in pending
            if row[2] in _CARRIED_FROM_THE_STORED_FILE
            # The store records a schema echo failed as it writes the row, and a SUCCESS
            # written after would replace that.
            and row[1] not in acc.echoed
        )
        pending = [row for row in pending if row[2] not in _CARRIED_FROM_THE_STORED_FILE]
    refused = _refusal_of(acc.storage_backend, pending, acc.action_name)
    if refused is not None and context is not None:
        context.dispositions_not_stored.update(row[1] for row in pending)
        failures = sorted({row[1] for row in pending if row[2] in FAILURE_DISPOSITIONS})
        if failures and context.failure_not_stored is None:
            context.failure_not_stored = failures_not_stored(acc.action_name, failures, refused)


def _report_collection(
    acc: _Collection,
    total_input: int,
    config: dict[str, Any],
    context: ProcessingContext | None,
) -> None:
    """Fire the completion event and log the all-filtered and tombstone summaries."""
    action_name = acc.action_name
    stats = acc.stats
    guard_config = config.get("guard", {})
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
            total_guard_skipped=acc.guard_skipped,
            total_deferred=stats["deferred"],
            total_sent_elsewhere=stats["sent_elsewhere"],
            guard_condition=guard_condition,
            guard_on_false=guard_on_false,
            target_relative_path=(context.target_relative_path or "") if context else "",
        )
    )

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
            total_input,
            stats["skipped"],
            stats["exhausted"],
            stats["unprocessed"],
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

    acc = _Collection(action_name=action_name, storage_backend=storage_backend)

    for idx, result in enumerate(results):
        status = result.status
        status_key = status.value
        acc.stats[status_key] += 1

        if status == ProcessingStatus.SUCCESS:
            _collect_success(acc, idx, result, status_key)
        elif status == ProcessingStatus.SKIPPED:
            _collect_skipped(acc, idx, result)
        elif status == ProcessingStatus.EXHAUSTED:
            _collect_exhausted(acc, idx, result)
        elif status == ProcessingStatus.FAILED:
            _collect_failed(acc, idx, result)
        elif status == ProcessingStatus.FILTERED:
            _collect_filtered(acc, idx, result, status_key, effective_config)
        elif status == ProcessingStatus.UNPROCESSED:
            _collect_unprocessed(acc, idx, result, status_key)
        elif status == ProcessingStatus.DEFERRED:
            _collect_deferred(acc, idx, result)
        else:
            logger.debug("Unhandled result status=%s", status)  # type: ignore[unreachable]

    _write_pending(acc, context)
    _report_collection(acc, len(results), effective_config, context)

    if storage_backend is not None:
        storage_backend.credit_rows_collected(action_name, len(acc.output) - acc.carried_rows)

    stats = acc.stats
    collection = CollectionStats(
        causes=tuple(acc.causes),
        success=stats["success"],
        failed=stats["failed"],
        skipped=stats["skipped"],
        filtered=stats["filtered"],
        exhausted=stats["exhausted"],
        deferred=stats["deferred"],
        unprocessed=stats["unprocessed"],
        carry_forward=stats["carry_forward"],
        carried_success=stats["carried_success"],
        sent_elsewhere=stats["sent_elsewhere"],
        cases=route_case_counts(effective_config, action_name, acc.routed),
        guard_skipped=acc.guard_skipped,
        checks_failed=len(acc.failed_guids) + acc.unidentified_failed,
    )
    add_collection(collection)
    return acc.output, collection


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
        retry = first.recovery_metadata.retry if first.recovery_metadata else None
        cause = f"{retry.last_error} — " if retry and retry.last_error else ""
        return AgentActionsError(
            f"{cause}Retry exhausted for record {first.source_guid} after "
            f"{_get_retry_attempts(first)} attempts (on_exhausted=raise)",
            context={
                "agent_name": agent_name,
                "exhausted_records": len(exhausted_results),
                "on_exhausted": "raise",
            },
        )
