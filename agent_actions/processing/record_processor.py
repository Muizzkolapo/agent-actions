"""Record-level processor: single-item processing pipeline."""

import json
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Optional, cast

from agent_actions.config.types import RunMode
from agent_actions.errors import ConfigurationError, SchemaValidationError
from agent_actions.errors.operations import TemplateVariableError
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.data_pipeline_events import (
    BatchDataProcessingCompleteEvent,
    BatchProcessingProgressEvent,
    BatchProcessingStartedEvent,
    RecordEmptyOutputEvent,
    RecordFilteredEvent,
    RecordProcessingCompleteEvent,
    RecordProcessingStartedEvent,
    RecordTransformedEvent,
)
from agent_actions.logging.events.llm_events import TemplateRenderingFailedEvent
from agent_actions.output.response.config_fields import get_default
from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS, RecordEnvelope
from agent_actions.utils.constants import HITL_FILE_GRANULARITY_ERROR
from agent_actions.utils.content import get_existing_content

from .enrichment import EnrichmentPipeline
from .exhausted_builder import ExhaustedRecordBuilder
from .invocation import BatchProvider, InvocationStrategy, InvocationStrategyFactory
from .prepared_task import GuardStatus, PreparationContext
from .task_preparer import TaskPreparer, get_task_preparer
from .types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)

logger = logging.getLogger(__name__)


def _is_empty_output(response: Any) -> bool:
    """Check if a tool/LLM response is effectively empty."""
    if response is None:
        return True
    if isinstance(response, dict | list) and len(response) == 0:
        return True
    return False


class RecordProcessor:
    """Unified processor for first-stage and subsequent-stage record processing."""

    @classmethod
    def create(
        cls,
        agent_config: dict[str, Any],
        agent_name: str,
    ) -> "RecordProcessor":
        """Create a RecordProcessor with standard online-mode defaults.

        Production code that needs custom strategy/mode/provider should
        use the constructor directly.
        """
        return cls(agent_config=agent_config, agent_name=agent_name)

    def __init__(
        self,
        agent_config: dict[str, Any],
        agent_name: str,
        strategy: InvocationStrategy | None = None,
        mode: RunMode = RunMode.ONLINE,
        provider: Optional["BatchProvider"] = None,
    ):
        self.agent_config = agent_config
        self.agent_name = agent_name

        if strategy is not None and (mode != RunMode.ONLINE or provider is not None):
            logger.warning(
                "Both 'strategy' and 'mode'/'provider' specified for %s; "
                "'strategy' takes precedence",
                agent_name,
            )

        granularity = agent_config.get("granularity", get_default("granularity"))
        action_kind = (agent_config.get("kind") or "").lower()

        # FILE granularity only allowed for tool and HITL actions
        is_file_granularity = isinstance(granularity, str) and granularity.lower() == "file"
        if is_file_granularity:
            if action_kind not in ["tool", "hitl"]:
                raise ConfigurationError(
                    "FILE granularity is only supported for tool and hitl actions. "
                    "LLM actions must use RECORD granularity.",
                    context={
                        "agent_name": agent_name,
                        "granularity": granularity,
                        "kind": action_kind or "(not set)",
                    },
                )

        # HITL actions require FILE granularity — Record mode launches a
        # separate approval UI per record, which is broken UX.
        if action_kind == "hitl" and not is_file_granularity:
            raise ConfigurationError(
                HITL_FILE_GRANULARITY_ERROR,
                context={
                    "agent_name": agent_name,
                    "granularity": granularity,
                    "kind": action_kind,
                },
            )

        self.enrichment_pipeline = EnrichmentPipeline()

        self._strategy = strategy or InvocationStrategyFactory.create(
            mode=mode,
            agent_config=agent_config,
            provider=provider,
        )

    def process(self, item: Any, context: ProcessingContext) -> ProcessingResult:
        """Process a single record through the full pipeline (prepare, invoke, transform, enrich)."""
        prep_context = PreparationContext.from_processing_context(context)
        prep_context.current_item = item if isinstance(item, dict) else None

        task_preparer = get_task_preparer()
        prepared = task_preparer.prepare(item, prep_context)

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

        if prepared.guard_status == GuardStatus.UPSTREAM_UNPROCESSED:
            preserved_item = dict(item) if isinstance(item, dict) else {"content": item}
            preserved_item["_unprocessed"] = True
            if not isinstance(preserved_item.get("metadata"), dict):
                preserved_item["metadata"] = {}
            if "agent_type" not in preserved_item["metadata"]:
                preserved_item["metadata"]["agent_type"] = "tombstone"
            result = ProcessingResult.unprocessed(
                data=[preserved_item],
                reason="upstream_unprocessed",
                source_guid=source_guid,
                source_snapshot=source_snapshot,
                input_record=input_record,
            )
            return self._finalize_result(result, context, source_guid)

        if prepared.guard_status == GuardStatus.FILTERED:
            fire_event(
                RecordFilteredEvent(
                    action_name=context.agent_name,
                    record_index=context.record_index,
                    source_guid=source_guid or "",
                    filter_reason="guard_filter",
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
            tombstone = self._build_tombstone_item(
                content,
                source_guid,
                f"guard_{prepared.guard_behavior}",
                input_record,
                context.action_name,
            )
            result = ProcessingResult.skipped(
                passthrough_data=tombstone,
                reason=f"guard_{prepared.guard_behavior}",
                source_guid=source_guid,
            )
            return self._finalize_result(result, context, source_guid)

        invocation_result = self._strategy.invoke(prepared, context)

        response = invocation_result.response
        executed = invocation_result.executed
        passthrough_fields = invocation_result.passthrough_fields
        recovery_metadata = invocation_result.recovery_metadata

        if (
            context.storage_backend is not None
            and executed
            and response is not None
            and source_guid is not None
        ):
            context.storage_backend.update_prompt_trace_response(
                action_name=context.agent_name,
                record_id=source_guid,
                response_text=json.dumps(response, ensure_ascii=False, default=str),
            )

        if invocation_result.deferred:
            return ProcessingResult.deferred(
                task_id=invocation_result.task_id or "",
                source_guid=source_guid,
                passthrough_fields=passthrough_fields,
                source_snapshot=source_snapshot,
                input_record=input_record,
            )

        if not executed:
            if response is None:
                if recovery_metadata and recovery_metadata.retry:
                    empty_content = ExhaustedRecordBuilder.build_empty_content(
                        cast(dict[str, Any], context.agent_config)
                    )
                    tombstone = self._build_tombstone_item(
                        empty_content,
                        source_guid,
                        "retry_exhausted",
                        input_record,
                        context.action_name,
                        extra_metadata={"retry_exhausted": True},
                    )
                    result = ProcessingResult.exhausted(
                        error=f"Retry exhausted after {recovery_metadata.retry.attempts} attempts",
                        data=[tombstone],
                        source_guid=source_guid,
                        recovery_metadata=recovery_metadata,
                        source_snapshot=source_snapshot,
                        input_record=input_record,
                    )
                    return self._finalize_result(result, context, source_guid)
                fire_event(
                    RecordFilteredEvent(
                        action_name=context.agent_name,
                        record_index=context.record_index,
                        source_guid=source_guid or "",
                        filter_reason="llm_layer_guard_filter",
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
                        filter_reason="llm_layer_guard_skip",
                    )
                )
                tombstone = self._build_tombstone_item(
                    response,
                    source_guid,
                    "guard_skip",
                    input_record,
                    context.action_name,
                )
                result = ProcessingResult.unprocessed(
                    data=[tombstone],
                    reason="guard_skip",
                    source_guid=source_guid,
                    source_snapshot=source_snapshot,
                    input_record=input_record,
                )
                return self._finalize_result(result, context, source_guid)

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

        item_existing_content = get_existing_content(item) if isinstance(item, dict) else None
        if not item_existing_content and isinstance(item, dict) and context.is_first_stage:
            raw = {k: v for k, v in item.items() if k not in RECORD_FRAMEWORK_FIELDS}
            if raw:
                item_existing_content = {"source": raw}
        transformed = self._transform_response(
            response,
            content,
            source_guid or "",
            passthrough_fields,
            context,
            existing_content=item_existing_content,
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

        result = ProcessingResult.success(
            data=transformed,
            source_guid=source_guid,
            passthrough_fields=passthrough_fields,
            source_snapshot=source_snapshot,
            raw_response=response,
            recovery_metadata=recovery_metadata,
            input_record=input_record,
        )

        return self._finalize_result(result, context, source_guid)

    def process_batch(self, items: list[Any], context: ProcessingContext) -> list[ProcessingResult]:
        """Process multiple records, capturing per-item failures without aborting the batch."""
        start_time = datetime.now(UTC)

        fire_event(
            BatchProcessingStartedEvent(
                action_name=context.agent_name,
                batch_size=len(items),
            )
        )

        results: list[ProcessingResult] = []
        successes = 0
        failures = 0

        for idx, item in enumerate(items):
            try:
                item_context = self._create_item_context(context, idx, item)
                result = self.process(item, item_context)
                results.append(result)

                if result.status == ProcessingStatus.SUCCESS:
                    successes += 1
                elif result.status == ProcessingStatus.FAILED:
                    failures += 1

                if (idx + 1) % 10 == 0 or (idx + 1) == len(items):
                    fire_event(
                        BatchProcessingProgressEvent(
                            action_name=context.agent_name,
                            processed=idx + 1,
                            total=len(items),
                            successes=successes,
                            failures=failures,
                        )
                    )

            except ConfigurationError:
                raise
            except EmptyOutputError:
                raise
            except TemplateVariableError as e:
                fire_event(
                    TemplateRenderingFailedEvent(
                        action_name=context.agent_name,
                        missing_variables=e.missing_variables,
                        error_message=str(e),
                    )
                )
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
                total_records=len(items),
                elapsed_time=elapsed_time,
            )
        )

        return results

    @staticmethod
    def _build_tombstone_item(
        content: Any,
        source_guid: str | None,
        reason: str,
        input_record: dict[str, Any] | None,
        action_name: str,
        *,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a tombstone item for guard-skipped, exhausted, or unprocessed records."""
        if reason.startswith("guard_"):
            item = RecordEnvelope.build_skipped(action_name, input_record)
        else:
            action_output = content if isinstance(content, dict) else {"value": content}
            item = RecordEnvelope.build(action_name, action_output, input_record)
        item["source_guid"] = source_guid
        item["metadata"] = {"reason": reason, "agent_type": "tombstone"}
        item["_unprocessed"] = True
        if extra_metadata:
            item["metadata"].update(extra_metadata)
        if input_record and isinstance(input_record, dict) and "target_id" in input_record:
            item["target_id"] = input_record["target_id"]
        return item

    def _finalize_result(
        self,
        result: ProcessingResult,
        context: ProcessingContext,
        source_guid: str | None,
    ) -> ProcessingResult:
        """Enrich a result and fire the completion event."""
        enriched_result = self.enrichment_pipeline.enrich(result, context)
        fire_event(
            RecordProcessingCompleteEvent(
                action_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid or "",
                status=enriched_result.status.value,
            )
        )
        return enriched_result

    def _transform_response(
        self,
        response: Any,
        content: Any,
        source_guid: str,
        passthrough_fields: dict[str, Any],
        context: ProcessingContext,
        existing_content: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Transform LLM response to output format."""
        from agent_actions.processing.helpers import (
            transform_with_passthrough,
        )

        return transform_with_passthrough(
            response,
            content,
            source_guid,
            cast(dict[str, Any], context.agent_config),
            action_name=context.action_name,
            passthrough_fields=passthrough_fields,
            existing_content=existing_content,
        )

    @staticmethod
    def _create_item_context(
        base_context: ProcessingContext, index: int, item: Any
    ) -> ProcessingContext:
        """Create per-item context with updated record_index."""
        return replace(
            base_context,
            record_index=index,
            current_item=item if isinstance(item, dict) else None,
        )
