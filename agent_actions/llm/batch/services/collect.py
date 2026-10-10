"""Collect a batch file's rows and write the file: once results are in, or with none.

Finalize and a run that sends nothing both come here, so every row is built, every
disposition written and every file stored by one path.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agent_actions.config.types import ActionConfigDict, RunMode
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.expectations.service import ExpectationConfigurationError
from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.writer import FileWriter
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.result_collector import CollectionStats
from agent_actions.processing.types import ProcessingContext, ProcessingResult, RecoveryMetadata
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.record.reasons import EMPTY_OUTPUT, GUARD_FILTER
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import DISPOSITION_DEFERRED, DISPOSITION_FILTERED
from agent_actions.utils.path_utils import ensure_directory_exists

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


@contextmanager
def halt_survives_failure(context: Any) -> Iterator[None]:
    """Keep a parked halt from being lost when something else fails first.

    Every early return past a park is guarded, but the exception exit is not a
    return: anything raised between the park and the finaliser unwinds past all
    of them. The outer loop answers a non-RuntimeError by logging it, failing
    that file's records and moving to the next file, so `on_exhausted: raise`
    would finish the run reporting success.

    The deliberate halt wins over the incidental failure, which is chained onto
    it rather than dropped. A clean pass leaves the halt parked for the finaliser.

    Typed loosely on purpose: two different objects carry a parked halt — the
    RecoveryContext the handlers pass around, and the ProcessingContext that
    collection parks on — and both need the same protection.
    """
    try:
        yield
    except ExpectationConfigurationError:
        # The one error kind that is already run-fatal: process_all_batch_results
        # re-raises it, because every remaining file carries the same broken
        # action config. Substituting the halt would only change its
        # classification — raised_by_exhaustion_policy would answer True, and the
        # workflow layer would then refuse to re-run the action and keep it out
        # of reset_retryable, so the operator fixes the YAML and stays stuck.
        #
        # Deliberately not the whole ConfigurationError family. The others are
        # per-record and the outer loop logs them and moves on, so passing one
        # through would take the parked halt with it and finish reporting success.
        raise
    except Exception as exc:
        pending = context.pending_exhaustion
        if pending is None:
            raise
        context.pending_exhaustion = None
        raise pending from exc


def _empty_output_halt(
    results: list[ProcessingResult], ctx: ProcessingContext
) -> EmptyOutputError | None:
    """The halt ``on_empty: error`` asks for, raised by the caller after the file is written."""
    if ctx.agent_config.get("on_empty", "warn") != "error":
        return None
    empty = [result.source_guid for result in results if result.skip_reason == EMPTY_OUTPUT]
    if not empty:
        return None
    return EmptyOutputError(
        f"Action '{ctx.agent_name}' produced empty output for {len(empty)} record(s) "
        f"(on_empty=error): {', '.join(str(guid) for guid in empty[:5])}",
        context={"agent_name": ctx.agent_name, "source_guids": empty},
    )


def _halt_for(results: list[ProcessingResult], ctx: ProcessingContext) -> Exception | None:
    """The one halt to raise for this file: the first parked, else the empty-output one."""
    empty = _empty_output_halt(results, ctx)
    if ctx.pending_exhaustion is not None and empty is not None:
        logger.warning(
            "on_empty: error also stopped this file; raising the halt already parked. %s", empty
        )
    return ctx.pending_exhaustion or empty


def collect_batch_rows(
    storage_backend: StorageBackend | None,
    action_name: str,
    agent_config: dict[str, Any] | None,
    context_map: dict[str, Any] | None,
    batch_results: list[BatchResult],
    *,
    output_directory: str | None,
    exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    result_processor: BatchResultStrategy | None = None,
    unified_processor: UnifiedProcessor | None = None,
) -> tuple[list[dict[str, Any]], CollectionStats, Exception | None]:
    """A batch file's rows, collected from *batch_results* against *context_map*.

    Every entry no result answers is collected as what preparation found it to be,
    so no results at all collects a run that sent nothing. The halt
    `on_exhausted: raise` or `on_empty: error` decided is returned, not raised: the
    caller raises it once the file is written.
    """
    config = {**(agent_config or {}), "action_name": action_name}
    results = (result_processor or BatchResultStrategy()).process(
        batch_results=batch_results,
        context_map=context_map,
        output_directory=output_directory,
        agent_config=config,
        exhausted_recovery=exhausted_recovery,
    )
    ctx = ProcessingContext(
        agent_config=cast(ActionConfigDict, config),
        agent_name=action_name,
        mode=RunMode.BATCH,
        storage_backend=storage_backend,
    )
    ctx.defer_exhaustion = True
    processor = unified_processor or UnifiedProcessor(enrichment_pipeline=EnrichmentPipeline())
    # Collection parks the halt partway through and keeps working. A failure after
    # that point would return no third element at all.
    with halt_survives_failure(ctx):
        rows, stats = processor.enrich_and_collect(results, ctx)
        if storage_backend is not None:
            clear_deferred_dispositions(storage_backend, action_name, rows)
            # The reconciler hands the collector no filtered entry.
            write_filtered_dispositions(storage_backend, action_name, context_map or {})
            update_prompt_trace_responses(storage_backend, action_name, rows)
    return rows, stats, _halt_for(results, ctx)


def write_batch_file(
    storage_backend: StorageBackend | None,
    action_name: str,
    rows: list[dict[str, Any]],
    *,
    output_root: str,
    stored_name: str,
    batch_inputs: Collection[str] = (),
) -> Path:
    """Store *rows* as the file *stored_name*, with every stored row they do not replace.

    The path is built from the name, never the other way round, so the file is
    stored under exactly *stored_name* whichever folder the caller was handed.
    *batch_inputs* is the file's input before narrowing: once the action above mints
    its own identities, the rows alone cannot say which producers still exist.
    """
    output_file = Path(output_root) / stored_name
    if storage_backend is None:
        ensure_directory_exists(output_file, is_file=True)
    else:
        from agent_actions.processing.disposition_gate import with_stored_rows_not_reproduced

        rows = with_stored_rows_not_reproduced(
            rows, action_name, stored_name, storage_backend, batch_inputs=batch_inputs
        )
    FileWriter(
        str(output_file),
        storage_backend=storage_backend,
        action_name=action_name,
        output_directory=output_root,
    ).write_target(rows)
    return output_file


def clear_deferred_dispositions(
    storage_backend: StorageBackend, action_name: str, rows: list[dict[str, Any]]
) -> None:
    """Clear the DEFERRED stamped at submission for each record entering output."""
    for row in rows:
        source_guid = row.get("source_guid")
        if source_guid:
            _try_clear_deferred(storage_backend, action_name, source_guid)


def write_filtered_dispositions(
    storage_backend: StorageBackend, action_name: str, context_map: dict[str, Any]
) -> None:
    """Write FILTERED for each record the guard filtered, as online's collector does."""
    for entry in context_map.values():
        if BatchContextMetadata.get_filter_status(entry) != FilterStatus.FILTERED:
            continue
        source_guid = entry.get("source_guid")
        if not source_guid:
            continue
        reason = BatchContextMetadata.get_skip_reason(entry) or GUARD_FILTER
        _try_clear_deferred(storage_backend, action_name, source_guid)
        try:
            storage_backend.set_disposition(
                action_name, source_guid, DISPOSITION_FILTERED, reason=reason
            )
        except Exception:
            logger.warning(
                "Failed to write FILTERED disposition for %s — "
                "record may be reprocessed on next run",
                source_guid,
                exc_info=True,
            )


def update_prompt_trace_responses(
    storage_backend: StorageBackend, action_name: str, rows: list[dict[str, Any]]
) -> None:
    """Record each answer on its prompt trace; a tombstone answered nothing."""
    try:
        for row in rows:
            if row.get("_state") != RecordState.PROCESSED.value:
                continue
            # An expansion child's target_id was re-minted after its prompt
            # ran, so it reaches the trace by parent_target_id.
            target_id = row.get("target_id")
            if not target_id:
                continue
            content = row.get("content")
            if content is None:
                continue
            # Extract only the action's output namespace — matches online prompt trace shape
            action_output = (
                content.get(action_name, content) if isinstance(content, dict) else content
            )
            response_text = json.dumps(action_output, ensure_ascii=False, default=str)
            storage_backend.update_prompt_trace_response(
                action_name=action_name,
                record_id=target_id,
                response_text=response_text,
                parent_record_id=row.get("parent_target_id"),
            )
    except Exception:
        logger.warning(
            "Failed to update prompt trace responses for batch action=%s",
            action_name,
            exc_info=True,
        )


def _try_clear_deferred(storage_backend: StorageBackend, action_name: str, record_id: str) -> None:
    try:
        storage_backend.clear_disposition(
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
