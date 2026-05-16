"""Online LLM processing strategy for UnifiedProcessor.

Handles per-record processing: prepare task, invoke LLM, handle response,
transform output.
"""

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError, RecordContextError, SchemaValidationError
from agent_actions.errors.operations import TemplateVariableError
from agent_actions.errors.processing import EmptyOutputError
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
from agent_actions.processing.cascade_filter import partition_cascade_records
from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.invocation import InvocationStrategy, InvocationStrategyFactory
from agent_actions.processing.prepared_task import GuardStatus, PreparationContext
from agent_actions.processing.record_helpers import (
    build_exhausted_tombstone,
    build_tombstone,
    carry_framework_fields,
    extract_existing_content,
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
    GUARD_FILTER,
    GUARD_SKIP,
    LLM_LAYER_GUARD_FILTER,
    LLM_LAYER_GUARD_SKIP,
    PREP_FAILED,
    UPSTREAM_UNPROCESSED,
)
from agent_actions.record.state import RecordState
from agent_actions.storage.backend import DISPOSITION_FAILED

logger = logging.getLogger(__name__)


def _is_empty_output(response: Any) -> bool:
    """Check if a tool/LLM response is effectively empty."""
    if response is None:
        return True
    if isinstance(response, dict | list) and len(response) == 0:
        return True
    return False


def _create_item_context(
    base_context: ProcessingContext, index: int, item: Any
) -> ProcessingContext:
    """Create per-item context with updated record_index."""
    return replace(
        base_context,
        record_index=index,
        current_item=item if isinstance(item, dict) else None,
    )


def _build_prep_failed_result(
    item: Any,
    context: ProcessingContext,
    error_msg: str,
) -> ProcessingResult:
    """Build a tombstone ProcessingResult for a record that failed prompt preparation."""
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

    return ProcessingResult.unprocessed(
        data=[tombstone],
        reason=PREP_FAILED,
        source_guid=source_guid,
        input_record=input_record,
    )


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

        Cascade-blocking records (FAILED/EXHAUSTED/CASCADE_SKIPPED from
        upstream) are partitioned out before processing — no LLM calls
        are made for quarantined records.

        Iterates remaining records, calling process_record() for each.
        Record-specific errors (RecordContextError, TemplateVariableError
        with missing vars) produce tombstones and continue. Action-fatal
        errors (ConfigurationError, TemplateSyntaxError, EmptyOutputError,
        SchemaValidationError) re-raise.
        """
        processable, quarantined_results = partition_cascade_records(
            records, action_name=context.agent_name
        )

        start_time = datetime.now(UTC)

        fire_event(
            BatchProcessingStartedEvent(
                action_name=context.agent_name,
                batch_size=len(processable),
            )
        )

        results: list[ProcessingResult] = list(quarantined_results)
        successes = 0
        failures = 0

        for idx, item in enumerate(processable):
            try:
                item_context = _create_item_context(context, idx, item)
                result = self.process_record(item, item_context)
                results.append(result)

                if result.status == ProcessingStatus.SUCCESS:
                    successes += 1
                elif result.status == ProcessingStatus.FAILED:
                    failures += 1

                if (idx + 1) % 10 == 0 or (idx + 1) == len(processable):
                    fire_event(
                        BatchProcessingProgressEvent(
                            action_name=context.agent_name,
                            processed=idx + 1,
                            total=len(processable),
                            successes=successes,
                            failures=failures,
                        )
                    )

            except RecordContextError as e:
                # Per-record recoverable — build tombstone, continue processing
                logger.warning(
                    "[%s] Record %d prep failed (context incomplete): %s",
                    context.agent_name,
                    idx,
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
                    # TemplateSyntaxError wrapped — broken template, action-fatal
                    raise
                # Missing variables — per-record recoverable
                logger.warning(
                    "[%s] Record %d prep failed (missing template vars): %s",
                    context.agent_name,
                    idx,
                    e,
                )
                result = _build_prep_failed_result(item, context, str(e))
                results.append(result)
                failures += 1
            except ConfigurationError:
                raise
            except EmptyOutputError:
                raise
            except SchemaValidationError:
                raise
            except Exception as e:
                logger.exception(
                    "[%s] Error processing item %d: %s",
                    context.agent_name,
                    idx,
                    str(e),
                )
                input_record = item if isinstance(item, dict) else None
                source_snapshot = None
                source_guid = None
                if context.is_first_stage:
                    from agent_actions.utils.id_generation import IDGenerator

                    source_guid = IDGenerator.generate_deterministic_source_guid(item)
                    source_snapshot = TaskPreparer._prepare_source_snapshot(item)
                else:
                    source_guid = item.get("source_guid") if isinstance(item, dict) else None
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
                total_records=len(processable),
                elapsed_time=elapsed_time,
            )
        )

        return results

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
                if recovery_metadata and recovery_metadata.retry:
                    empty_content = ExhaustedRecordBuilder.build_empty_content(
                        cast(dict[str, Any], context.agent_config)
                    )
                    tombstone = build_exhausted_tombstone(
                        context.action_name,
                        input_record,
                        empty_content,
                        source_guid=source_guid,
                    )
                    return ProcessingResult.exhausted(
                        error=f"Retry exhausted after {recovery_metadata.retry.attempts} attempts",
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

        # Transform response
        item_existing_content = (
            extract_existing_content(item, is_first_stage=context.is_first_stage)
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
