"""Online LLM processing strategy for UnifiedProcessor.

Handles per-record processing: prepare task, invoke LLM, handle response,
transform output.
"""

import json
import logging
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from agent_actions.config.types import ActionConfigDict, RunMode
from agent_actions.errors import (
    ConfigurationError,
    RecordContextError,
    SchemaValidationError,
    mark_action_fatal,
    raised_by_exhaustion_policy,
)
from agent_actions.errors.operations import TemplateVariableError
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.expectations.service import ExpectationsExhaustedError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.data_pipeline_events import (
    BatchDataProcessingCompleteEvent,
    BatchProcessingProgressEvent,
    BatchProcessingStartedEvent,
    RecordEmptyOutputEvent,
    RecordFilteredEvent,
    RecordProcessingStartedEvent,
    RecordTransformedEvent,
)
from agent_actions.logging.events.llm_events import TemplateRenderingFailedEvent
from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.helpers import _is_empty_output
from agent_actions.processing.invocation import InvocationStrategy, InvocationStrategyFactory
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.record_helpers import (
    build_exhausted_tombstone,
    build_tombstone,
    carry_framework_fields,
    derive_relative_path,
)
from agent_actions.processing.result_collector import _safe_set_disposition
from agent_actions.processing.task_preparer import TaskPreparer, get_task_preparer
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.reasons import (
    EMPTY_OUTPUT,
    EXPECTATIONS_EXHAUSTED,
    GUARD_FILTER,
    GUARD_SKIP,
    LLM_LAYER_GUARD_FILTER,
    LLM_LAYER_GUARD_SKIP,
    PREP_FAILED,
    REPROMPT_EXHAUSTED,
    RETRY_EXHAUSTED,
    UPSTREAM_UNPROCESSED,
)
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import DISPOSITION_FAILED, DISPOSITION_SUCCESS
from agent_actions.utils.content import get_existing_content
from agent_actions.utils.schema_echo import is_schema_echo, make_schema_echo_error

logger = logging.getLogger(__name__)


def _empty_warn_reason(
    action_config: ActionConfigDict, agent_name: str, source_guid: str | None
) -> str:
    """Reason text for the on_empty=warn branch; tool-aware for tool actions.

    A tool action is identified by either `kind` or `model_vendor` being
    ``"tool"`` (the same signal that routed and executed it as a tool), so the
    reason names the empty tool output rather than blaming the LLM.
    """
    if action_config.get("kind") == "tool" or action_config.get("model_vendor") == "tool":
        return f"Tool '{agent_name}' returned an empty list of records for input {source_guid}"
    return f"Empty LLM response for record '{source_guid}'"


def _create_item_context(
    base_context: ProcessingContext, index: int, item: Any
) -> ProcessingContext:
    """Create per-item context with updated record_index."""
    return replace(
        base_context,
        record_index=index,
        current_item=item if isinstance(item, dict) else None,
    )


def _reject_schema_echo_result(result: ProcessingResult, action_name: str) -> ProcessingResult:
    """Fail a result whose action namespace is the compiled schema, not conforming output.

    The executed-LLM path rejects echoes in ``transform_with_passthrough``; this is the
    funnel every result crosses before checkpoint/collection, so any branch that plants a
    schema echo is caught here — the namespace becomes ``_parse_error`` and the result
    becomes FAILED, keeping status and persisted data consistent (never a silent success).
    """
    if not result.data:
        return result
    sanitized: list[dict[str, Any]] = []
    changed = False
    for record in result.data:
        content = record.get("content") if isinstance(record, dict) else None
        if isinstance(content, dict) and is_schema_echo(content.get(action_name)):
            changed = True
            sanitized.append(
                {
                    **record,
                    "content": {
                        **content,
                        action_name: make_schema_echo_error(content[action_name]),
                    },
                }
            )
        else:
            sanitized.append(record)
    if not changed:
        return result
    logger.warning(
        "[%s] Schema-echo namespace in a %s result (source_guid=%s) — "
        "converting to parse-error and failing the record.",
        action_name,
        result.status.value,
        result.source_guid,
    )
    return replace(
        result,
        status=ProcessingStatus.FAILED,
        data=sanitized,
        error="Schema-echo: action namespace was the compiled schema, not conforming output",
    )


def _build_prep_failed_result(
    item: Any,
    context: ProcessingContext,
    error_msg: str,
) -> ProcessingResult:
    """Build a FAILED ProcessingResult for a record that failed prompt preparation.

    A prep failure is a genuine failure of this action, not upstream
    cascade-quarantine, so it is classified FAILED (matching the batch path) and
    counts toward terminal-failure detection. The tombstone preserves lineage so
    downstream actions still see the record and cascade-skip it.
    """
    input_record = item if isinstance(item, dict) else None
    source_guid = input_record.get("source_guid") if input_record else None

    tombstone = build_tombstone(
        action_name=context.agent_name,
        input_record=input_record,
        reason=PREP_FAILED,
        source_guid=source_guid,
    )
    RecordEnvelope.transition(tombstone, RecordState.FAILED, context.agent_name, error_msg[:200])

    if context.storage_backend and source_guid:
        _safe_set_disposition(
            context.storage_backend,
            context.agent_name,
            source_guid,
            DISPOSITION_FAILED,
            reason=error_msg[:500],
        )

    result = ProcessingResult.failed(
        error=error_msg,
        source_guid=source_guid,
        input_record=input_record,
    )
    result.data = [tombstone]
    result.skip_reason = PREP_FAILED
    return result


class OnlineLLMStrategy:
    """Online LLM processing strategy for UnifiedProcessor.

    Handles per-record: prepare task -> invoke LLM -> handle response -> transform.
    Does NOT perform enrichment (handled by UnifiedProcessor).
    """

    def __init__(
        self,
        agent_config: dict[str, Any],
        agent_name: str,
        invocation_strategy: InvocationStrategy | None = None,
    ) -> None:
        self._agent_config = agent_config
        self._agent_name = agent_name
        self._invocation_strategy = invocation_strategy or InvocationStrategyFactory.create(
            mode=RunMode.ONLINE,
            agent_config=agent_config,
        )

    def invoke(
        self,
        records: list[dict[str, Any]],
        context: ProcessingContext,
    ) -> list[ProcessingResult]:
        """Process records through the online LLM pipeline.

        Records arrive already cascade-filtered by UnifiedProcessor.
        Per-record errors (RecordContextError, missing template vars) become
        tombstones and the pass continues; action-fatal errors re-raise marked,
        so the layers above can tell a broken action from one bad input.
        """
        start_time = datetime.now(UTC)

        fire_event(
            BatchProcessingStartedEvent(
                action_name=context.agent_name,
                batch_size=len(records),
            )
        )

        results: list[ProcessingResult] = []
        successes = 0
        failures = 0

        for idx, item in enumerate(records):
            try:
                item_context = _create_item_context(context, idx, item)
                result = self.process_record(item, item_context)
                result = _reject_schema_echo_result(result, context.action_name)
                results.append(result)

                if result.status == ProcessingStatus.SUCCESS:
                    successes += 1
                elif result.status == ProcessingStatus.FAILED:
                    failures += 1

                # Checkpoint: commit this record's result to SQLite immediately
                # so interrupted runs can resume from where they left off.
                if context.storage_backend and result.source_guid:
                    self._checkpoint_record(result, context)

                if (idx + 1) % 10 == 0 or (idx + 1) == len(records):
                    fire_event(
                        BatchProcessingProgressEvent(
                            action_name=context.agent_name,
                            processed=idx + 1,
                            total=len(records),
                            successes=successes,
                            failures=failures,
                        )
                    )

            except RecordContextError as e:
                # Per-record recoverable — build tombstone, continue processing
                record_id = item.get("source_guid", idx) if isinstance(item, dict) else idx
                logger.warning(
                    "[%s] Record %s prep failed (context incomplete): %s",
                    context.agent_name,
                    record_id,
                    e,
                )
                result = _build_prep_failed_result(item, context, str(e))
                results.append(result)
                failures += 1
            except TemplateVariableError as e:
                fire_event(
                    TemplateRenderingFailedEvent(
                        action_name=context.agent_name,
                        missing_variables=e.missing_variables,
                        error_message=str(e),
                    )
                )
                if not e.missing_variables:
                    # No variable to blame: a malformed template (already marked
                    # action-fatal where it was parsed) or a render failure this
                    # record's data provoked. Either way, not a tombstone.
                    raise
                # Missing variables — per-record recoverable
                record_id = item.get("source_guid", idx) if isinstance(item, dict) else idx
                logger.warning(
                    "[%s] Record %s prep failed (missing template vars): %s",
                    context.agent_name,
                    record_id,
                    e,
                )
                result = _build_prep_failed_result(item, context, str(e))
                results.append(result)
                failures += 1
            except (ConfigurationError, EmptyOutputError) as e:
                mark_action_fatal(e)
                raise
            except SchemaValidationError:
                # UDF output validation runs per item and is ungated, so this
                # can indict one value rather than the action. Re-raised, as
                # the loop cannot tombstone it, but not declared fatal.
                raise
            except ExpectationsExhaustedError:
                # on_exhausted: raise means halt the run, not fail the record.
                raise
            except Exception as e:
                # An on_exhausted: raise halt is action-fatal by definition —
                # the config asked the run to stop. Flattening it into a record
                # result discards the policy with the exception.
                if raised_by_exhaustion_policy(e):
                    raise
                logger.exception(
                    "[%s] Error processing item %d: %s",
                    context.agent_name,
                    idx,
                    str(e),
                )
                input_record = item if isinstance(item, dict) else None
                # Read the stamped guid — a first-stage record is stamped at
                # ingestion/unified before processing, so re-deriving here would hash the
                # now-stamped item and diverge from the persisted source_data key.
                source_guid = input_record.get("source_guid") if input_record else None
                source_snapshot = (
                    TaskPreparer._prepare_source_snapshot(item) if context.is_first_stage else None
                )
                failed_result = ProcessingResult.failed(
                    error=f"Error processing item {idx}: {str(e)}",
                    source_guid=source_guid,
                    source_snapshot=source_snapshot,
                    input_record=input_record,
                )
                results.append(failed_result)
                failures += 1

        elapsed_time = (datetime.now(UTC) - start_time).total_seconds()
        fire_event(
            BatchDataProcessingCompleteEvent(
                action_name=context.agent_name,
                total_records=len(records),
                elapsed_time=elapsed_time,
            )
        )

        return results

    @staticmethod
    def _checkpoint_record(result: ProcessingResult, context: ProcessingContext) -> None:
        """Write a single record's disposition and output to SQLite immediately.

        Called after each record's LLM call completes so that interrupted
        runs can resume via the DispositionGate carry-forward path.
        """
        backend = context.storage_backend
        if not backend or not result.source_guid:
            return

        disposition = (
            DISPOSITION_SUCCESS if result.status == ProcessingStatus.SUCCESS else DISPOSITION_FAILED
        )
        reason = result.error if result.status == ProcessingStatus.FAILED else None

        try:
            backend.set_disposition(
                context.action_name,
                result.source_guid,
                disposition,
                reason=reason,
            )
            if result.data:
                relative_path = derive_relative_path(context.file_path, context.output_directory)
                if relative_path:
                    # Copy records to avoid mutating result.data in-place —
                    # downstream consumers (enrichment, collectors) hold
                    # references to the same dicts.
                    checkpoint_records = [
                        {**item, "_state": RecordState.PROCESSED}
                        if isinstance(item, dict) and "_state" not in item
                        else item
                        for item in result.data
                    ]
                    backend.save_checkpoint_records(
                        context.action_name, relative_path, checkpoint_records
                    )
            logger.info(
                "[%s] Checkpointed record %s (%s)",
                context.action_name,
                result.source_guid,
                disposition,
            )
        except (OSError, sqlite3.Error):
            logger.warning(
                "[%s] Checkpoint write failed for %s — will reprocess on resume",
                context.action_name,
                result.source_guid,
                exc_info=True,
            )

    def process_record(
        self, item: Any, context: ProcessingContext, *, skip_guard: bool = False
    ) -> ProcessingResult:
        """Process a single record: prepare, invoke LLM, handle response, transform.

        Args:
            skip_guard: When False (default), per-record guard evaluates with
                full context from TaskPreparer._load_full_context().  The
                prefilter in UnifiedProcessor is a fast-path optimization;
                per-record guard is the authoritative evaluation.

        Does NOT enrich the result — enrichment is handled by UnifiedProcessor.
        """
        prep_context = PreparationContext.from_processing_context(context)
        prep_context.current_item = item if isinstance(item, dict) else None

        task_preparer = get_task_preparer()
        prepared = task_preparer.prepare(item, prep_context, skip_guard=skip_guard)

        input_record = item if isinstance(item, dict) else None
        source_guid = prepared.source_guid
        source_snapshot = prepared.source_snapshot
        content = prepared.original_content

        fire_event(
            RecordProcessingStartedEvent(
                action_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid or "",
            )
        )

        # Upstream unprocessed — passthrough as tombstone
        if prepared.guard_status == GuardStatus.UPSTREAM_UNPROCESSED:
            tombstone = build_tombstone(
                context.action_name,
                input_record,
                UPSTREAM_UNPROCESSED,
                source_guid=source_guid,
            )
            return ProcessingResult.unprocessed(
                data=[tombstone],
                reason=UPSTREAM_UNPROCESSED,
                source_guid=source_guid,
                source_snapshot=source_snapshot,
                input_record=input_record,
            )

        # Per-record guard outcomes (only when skip_guard=False)
        if prepared.guard_status == GuardStatus.FILTERED:
            fire_event(
                RecordFilteredEvent(
                    action_name=context.agent_name,
                    record_index=context.record_index,
                    source_guid=source_guid or "",
                    filter_reason=GUARD_FILTER,
                )
            )
            return ProcessingResult.filtered(
                source_guid=source_guid,
                source_snapshot=source_snapshot,
                input_record=input_record,
            )

        if prepared.guard_status == GuardStatus.SKIPPED:
            fire_event(
                RecordFilteredEvent(
                    action_name=context.agent_name,
                    record_index=context.record_index,
                    source_guid=source_guid or "",
                    filter_reason=f"guard_{prepared.guard_behavior}",
                )
            )
            tombstone = build_tombstone(
                context.action_name,
                input_record,
                f"guard_{prepared.guard_behavior}",
                source_guid=source_guid,
            )
            return ProcessingResult.skipped(
                passthrough_data=tombstone,
                reason=f"guard_{prepared.guard_behavior}",
                source_guid=source_guid,
                source_snapshot=source_snapshot,
                input_record=input_record,
            )

        # Invoke the LLM strategy
        invocation_result = self._invocation_strategy.invoke(prepared, context)

        response = invocation_result.response
        executed = invocation_result.executed
        passthrough_fields = invocation_result.passthrough_fields
        recovery_metadata = invocation_result.recovery_metadata

        # Update prompt trace in storage
        if context.storage_backend is not None and executed and response is not None:
            context.storage_backend.update_prompt_trace_response(
                action_name=context.agent_name,
                record_id=prepared.target_id,
                response_text=json.dumps(response, ensure_ascii=False, default=str),
            )

        # Deferred (batch mode)
        if invocation_result.deferred:
            return ProcessingResult.deferred(
                task_id=invocation_result.task_id or "",
                source_guid=source_guid,
                passthrough_fields=passthrough_fields,
                source_snapshot=source_snapshot,
                input_record=input_record,
            )

        # Not executed — exhausted, filtered, or guard skip
        if not executed:
            if response is None:
                if recovery_metadata and (
                    recovery_metadata.retry
                    or recovery_metadata.reprompt
                    or recovery_metadata.expectations
                ):
                    empty_content = ExhaustedRecordBuilder.build_empty_content(
                        cast(dict[str, Any], context.agent_config)
                    )
                    extra_metadata: dict[str, Any] | None = None
                    if recovery_metadata.expectations:
                        # Expectations wrap the inner recovery layers, so their
                        # exhaustion is the terminal cause even when inner retry
                        # metadata is also present.
                        expectations = recovery_metadata.expectations
                        tombstone_reason = EXPECTATIONS_EXHAUSTED
                        error_msg = (
                            f"Expectations exhausted after {expectations.attempts} iteration(s) "
                            f"(failed: {', '.join(expectations.failed) or 'none recorded'})"
                        )
                        extra_metadata = {
                            "expectations_failed": expectations.failed,
                            "expectations_iterations": expectations.attempts,
                        }
                    elif recovery_metadata.retry:
                        tombstone_reason = RETRY_EXHAUSTED
                        error_msg = (
                            f"Retry exhausted after {recovery_metadata.retry.attempts} attempts"
                        )
                    else:
                        reprompt = recovery_metadata.reprompt
                        assert reprompt is not None
                        tombstone_reason = REPROMPT_EXHAUSTED
                        error_msg = (
                            f"Reprompt exhausted after {reprompt.attempts} attempts "
                            f"(validation: {reprompt.validation})"
                        )
                    tombstone = build_exhausted_tombstone(
                        context.action_name,
                        input_record,
                        empty_content,
                        source_guid=source_guid,
                        extra_metadata=extra_metadata,
                        reason=tombstone_reason,
                    )
                    return ProcessingResult.exhausted(
                        error=error_msg,
                        data=[tombstone],
                        source_guid=source_guid,
                        recovery_metadata=recovery_metadata,
                        source_snapshot=source_snapshot,
                        input_record=input_record,
                    )
                fire_event(
                    RecordFilteredEvent(
                        action_name=context.agent_name,
                        record_index=context.record_index,
                        source_guid=source_guid or "",
                        filter_reason=LLM_LAYER_GUARD_FILTER,
                    )
                )
                return ProcessingResult.filtered(
                    source_guid=source_guid,
                    source_snapshot=source_snapshot,
                    input_record=input_record,
                )
            else:
                fire_event(
                    RecordFilteredEvent(
                        action_name=context.agent_name,
                        record_index=context.record_index,
                        source_guid=source_guid or "",
                        filter_reason=LLM_LAYER_GUARD_SKIP,
                    )
                )
                tombstone = build_tombstone(
                    context.action_name,
                    input_record,
                    GUARD_SKIP,
                    source_guid=source_guid,
                )
                return ProcessingResult.skipped(
                    passthrough_data=tombstone,
                    reason=GUARD_SKIP,
                    source_guid=source_guid,
                    source_snapshot=source_snapshot,
                    input_record=input_record,
                )

        # Empty output handling
        if _is_empty_output(response):
            on_empty = context.agent_config.get("on_empty", "warn")
            input_field_count = len(content) if isinstance(content, dict) else 0

            fire_event(
                RecordEmptyOutputEvent(
                    action_name=context.agent_name,
                    record_index=context.record_index,
                    source_guid=source_guid or "",
                    input_field_count=input_field_count,
                    output=response,
                    on_empty=on_empty,
                )
            )

            if on_empty == "error":
                raise EmptyOutputError(
                    f"Action '{context.agent_name}' produced empty output for record "
                    f"'{source_guid}' (on_empty=error)",
                    context={
                        "agent_name": context.agent_name,
                        "source_guid": source_guid,
                        "output": str(response),
                    },
                )

            if on_empty == "warn":
                return ProcessingResult.failed(
                    error=_empty_warn_reason(context.agent_config, context.agent_name, source_guid),
                    source_guid=source_guid,
                    source_snapshot=source_snapshot,
                    input_record=input_record,
                )

            # on_empty == "skip": produce tombstone so record is visible in output
            tombstone = build_tombstone(
                context.action_name,
                input_record,
                EMPTY_OUTPUT,
                source_guid=source_guid,
            )
            return ProcessingResult.skipped(
                passthrough_data=tombstone,
                reason=EMPTY_OUTPUT,
                source_guid=source_guid,
                source_snapshot=source_snapshot,
                input_record=input_record,
            )

        # Transform response
        item_existing_content = (
            get_existing_content(item, is_first_stage=context.is_first_stage)
            if isinstance(item, dict)
            else None
        )
        transformed = self._transform_response(
            response,
            content,
            source_guid or "",
            passthrough_fields,
            context,
            existing_content=item_existing_content,
            input_record=input_record,
        )

        # Carry prepared.target_id to output records so the prompt trace
        # (keyed by target_id) can be matched by the scanner.
        # Uses a synthetic source dict because prepared.target_id may not
        # exist on input_record for first-stage actions where the ID is
        # generated by TaskPreparer.prepare().
        for record in transformed:
            if isinstance(record, dict):
                carry_framework_fields(
                    {"target_id": prepared.target_id},
                    record,
                    fields=("target_id",),
                )

        input_size = 1 if not isinstance(response, list) else len(response)
        output_size = len(transformed) if isinstance(transformed, list) else 1
        fire_event(
            RecordTransformedEvent(
                action_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid or "",
                input_size=input_size,
                output_size=output_size,
            )
        )

        return ProcessingResult.success(
            data=transformed,
            source_guid=source_guid,
            passthrough_fields=passthrough_fields,
            source_snapshot=source_snapshot,
            raw_response=response,
            recovery_metadata=recovery_metadata,
            input_record=input_record,
            is_expansion=len(transformed) > 1,
        )

    def _transform_response(
        self,
        response: Any,
        content: Any,
        source_guid: str,
        passthrough_fields: dict[str, Any],
        context: ProcessingContext,
        existing_content: dict[str, Any] | None = None,
        input_record: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Transform LLM response to output format."""
        from agent_actions.processing.helpers import transform_with_passthrough

        return transform_with_passthrough(
            response,
            content,
            source_guid,
            cast(dict[str, Any], context.agent_config),
            action_name=context.action_name,
            passthrough_fields=passthrough_fields,
            existing_content=existing_content,
            input_record=input_record,
        )
