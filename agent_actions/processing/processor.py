"""Unified record processor replacing StagingProcessor and TargetContentProcessor."""

import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Optional

from agent_actions.errors import ConfigurationError, SchemaValidationError
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.errors.operations import TemplateVariableError
from agent_actions.logging import fire_event
from agent_actions.logging.events.types import (
    TemplateRenderingFailedEvent,
    RecordProcessingStartedEvent,
    RecordFilteredEvent,
    RecordTransformedEvent,
    RecordProcessingCompleteEvent,
    RecordEmptyOutputEvent,
    BatchProcessingStartedEvent,
    BatchProcessingProgressEvent,
    BatchProcessingCompleteEvent,
)
from .enrichment import EnrichmentPipeline
from .exhausted_builder import ExhaustedRecordBuilder
from .invocation import BatchProvider, InvocationStrategy, InvocationStrategyFactory
from .prepared_task import GuardStatus, PreparationContext
from .task_preparer import TaskPreparer, get_task_preparer
from .types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    ProcessingStatus,
)

logger = logging.getLogger(__name__)


def _is_empty_output(response: Any) -> bool:
    """Check if a tool/LLM response is effectively empty."""
    if response is None:
        return True
    if isinstance(response, (dict, list)) and len(response) == 0:
        return True
    return False


class RecordProcessor:
    """
    Unified processor replacing StagingProcessor + TargetContentProcessor._process_single_item().

    Handles both first-stage (raw input) and subsequent-stage (structured input) processing.

    Architecture (Phase 3):
    -----------------------
    Uses InvocationStrategy pattern for flexible LLM execution:
    - OnlineStrategy: Synchronous execution with retry/reprompt
    - BatchStrategy: Queue tasks for batch API submission

    Guard Evaluation:
    -----------------
    Guards are evaluated ONCE via TaskPreparer, after prompt preparation,
    with full context available (input fields, source.*, passthrough fields).

    This is like a SQL WHERE clause - simple and predictable.

    Example:
    --------
    # Default usage (OnlineStrategy with configured recovery)
    processor = RecordProcessor(agent_config, agent_name)
    result = processor.process(item, context)

    # Custom strategy injection
    strategy = BatchStrategy(provider)
    processor = RecordProcessor(agent_config, agent_name, strategy=strategy)

    guard:
      clause: "status == 'active' and source.priority == 'high'"
      behavior: "skip"
    # → Guard has access to all fields, evaluated once before LLM call
    """

    def __init__(
        self,
        agent_config: dict[str, Any],
        agent_name: str,
        strategy: Optional[InvocationStrategy] = None,
        mode: ProcessingMode = ProcessingMode.ONLINE,
        provider: Optional["BatchProvider"] = None,
    ):
        """
        Initialize RecordProcessor.

        Args:
            agent_config: Agent configuration dict
            agent_name: Agent name for metadata
            strategy: Optional invocation strategy (overrides mode-based selection)
            mode: Processing mode for default strategy selection (ONLINE or BATCH)
            provider: Batch provider (required when mode=BATCH and no strategy given)
        """
        self.agent_config = agent_config
        self.agent_name = agent_name

        if strategy is not None and (mode != ProcessingMode.ONLINE or provider is not None):
            logger.warning(
                "Both 'strategy' and 'mode'/'provider' specified for %s; "
                "'strategy' takes precedence",
                agent_name,
            )

        # Validate granularity setting
        # kind: "tool" = tool action, "hitl" = HITL action, "llm" = LLM action (default)
        granularity = agent_config.get("granularity", "record")
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

            # Guards not supported in FILE mode (processes entire array at once)
            guard_config = agent_config.get("guard")
            if guard_config:
                raise ConfigurationError(
                    "Guards are not supported with FILE granularity. "
                    "FILE mode processes the entire array at once, so per-record guards cannot be applied. "
                    "Remove the guard or use RECORD granularity.",
                    context={
                        "agent_name": agent_name,
                        "granularity": granularity,
                        "kind": action_kind,
                        "guard": guard_config,
                    },
                )

        self.enrichment_pipeline = EnrichmentPipeline()

        # Initialize invocation strategy (honors mode when no explicit strategy given)
        self._strategy = strategy or InvocationStrategyFactory.create(
            mode=mode,
            agent_config=agent_config,
            provider=provider,
        )

    def process(self, item: Any, context: ProcessingContext) -> ProcessingResult:
        """
        Process single record (first-stage or subsequent-stage).

        Processing Pipeline:
        1-4. Prepare task (via TaskPreparer): normalize, source, prompt, guard
        5. Execute LLM
        6. Handle non-execution (retry exhausted)
        7. Detect empty output
        8. Transform response
        9. Create success result
        10. Enrich (lineage, metadata, loop IDs, etc.)

        Guard is evaluated ONCE in TaskPreparer, after prompt preparation,
        with full context available (like SQL WHERE).

        Args:
            item: Input item
                - First-stage: any type (str, list, dict, etc.)
                - Subsequent-stage: dict with {content, source_guid} (recommended)
            context: ProcessingContext with config and state

        Returns:
            ProcessingResult with enriched data
        """
        # Steps 1-4: Prepare task via TaskPreparer (unified preparation logic)
        prep_context = PreparationContext.from_processing_context(context)
        prep_context.current_item = item if isinstance(item, dict) else None

        task_preparer = get_task_preparer()
        prepared = task_preparer.prepare(item, prep_context)

        # Extract key fields for backward compatibility and event firing
        input_record = item if isinstance(item, dict) else None
        source_guid = prepared.source_guid
        source_snapshot = prepared.source_snapshot
        content = prepared.original_content

        # Fire RP001: Record processing started
        # Fires for ALL records including unprocessed — intentional so observability
        # sees the record was received. The immediately-following CompleteEvent with
        # status="unprocessed" closes the span.
        fire_event(
            RecordProcessingStartedEvent(
                agent_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid,
            )
        )

        # Handle upstream unprocessed records (dead/failed/skipped by prior action)
        # No RecordFilteredEvent here — these records aren't filtered (they're preserved
        # in output with lineage). RecordProcessingCompleteEvent below captures the status.
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

        # Handle Phase 1 guard results (filtered/skipped)
        if prepared.guard_status == GuardStatus.FILTERED:
            fire_event(
                RecordFilteredEvent(
                    agent_name=context.agent_name,
                    record_index=context.record_index,
                    source_guid=source_guid,
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
                    agent_name=context.agent_name,
                    record_index=context.record_index,
                    source_guid=source_guid,
                    filter_reason=f"guard_{prepared.guard_behavior}",
                )
            )
            tombstone = self._build_tombstone_item(
                content,
                source_guid,
                f"guard_{prepared.guard_behavior}",
                input_record,
            )
            result = ProcessingResult.unprocessed(
                data=[tombstone],
                reason=f"guard_{prepared.guard_behavior}",
                source_guid=source_guid,
                source_snapshot=source_snapshot,
                input_record=input_record,
            )
            return self._finalize_result(result, context, source_guid)

        # Step 5: Execute LLM via invocation strategy
        # Guard evaluation already done in TaskPreparer (strategy uses skip_guard_eval=True)
        invocation_result = self._strategy.invoke(prepared, context)

        # Extract results from InvocationResult
        response = invocation_result.response
        executed = invocation_result.executed
        passthrough_fields = invocation_result.passthrough_fields
        recovery_metadata = invocation_result.recovery_metadata

        # Step 6a: Handle deferred execution (batch mode)
        if invocation_result.deferred:
            return ProcessingResult.deferred(
                task_id=invocation_result.task_id,
                source_guid=source_guid,
                passthrough_fields=passthrough_fields,
                source_snapshot=source_snapshot,
                input_record=input_record,
            )

        # Step 6b: Handle non-execution (retry exhausted)
        # Note: Guards are evaluated ONCE in TaskPreparer, so executed=False here means
        # retry exhaustion, not guard filtering
        if not executed:
            if response is None:
                # Check if this is a retry exhaustion vs guard filter
                if recovery_metadata and recovery_metadata.retry:
                    # Build exhausted record with empty schema content for enrichment
                    empty_content = ExhaustedRecordBuilder.build_empty_content(context.agent_config)
                    tombstone = self._build_tombstone_item(
                        empty_content,
                        source_guid,
                        "retry_exhausted",
                        input_record,
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
                # Fire RP002: Record filtered (LLM layer guard filter)
                fire_event(
                    RecordFilteredEvent(
                        agent_name=context.agent_name,
                        record_index=context.record_index,
                        source_guid=source_guid,
                        filter_reason="llm_layer_guard_filter",
                    )
                )
                return ProcessingResult.filtered(
                    source_guid=source_guid,
                    source_snapshot=source_snapshot,
                    input_record=input_record,
                )
            else:
                # response is not None - guard caused skip rather than filter
                # Fire RP002: Record filtered (LLM layer guard skip)
                fire_event(
                    RecordFilteredEvent(
                        agent_name=context.agent_name,
                        record_index=context.record_index,
                        source_guid=source_guid,
                        filter_reason="llm_layer_guard_skip",
                    )
                )
                tombstone = self._build_tombstone_item(
                    response,
                    source_guid,
                    "guard_skip",
                    input_record,
                )
                result = ProcessingResult.unprocessed(
                    data=[tombstone],
                    reason="guard_skip",
                    source_guid=source_guid,
                    source_snapshot=source_snapshot,
                    input_record=input_record,
                )
                return self._finalize_result(result, context, source_guid)

        # Step 7: Detect empty output (before transform to avoid wasted work)
        if _is_empty_output(response):
            on_empty = context.agent_config.get("on_empty", "warn")
            input_field_count = len(content) if isinstance(content, dict) else 0

            # Always fire the event for observability; on_empty controls severity
            fire_event(
                RecordEmptyOutputEvent(
                    agent_name=context.agent_name,
                    record_index=context.record_index,
                    source_guid=source_guid,
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

        # Step 8: Transform response
        transformed = self._transform_response(
            response, content, source_guid, passthrough_fields, context
        )

        # Fire RP003: Record transformed
        input_size = 1 if not isinstance(response, list) else len(response)
        output_size = len(transformed) if isinstance(transformed, list) else 1
        fire_event(
            RecordTransformedEvent(
                agent_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid,
                input_size=input_size,
                output_size=output_size,
            )
        )

        # Step 9: Create success result (with recovery metadata if retry occurred)
        result = ProcessingResult.success(
            data=transformed,
            source_guid=source_guid,
            passthrough_fields=passthrough_fields,
            source_snapshot=source_snapshot,
            raw_response=response,
            recovery_metadata=recovery_metadata,
            input_record=input_record,
        )

        # Step 10: Enrich and finalize
        return self._finalize_result(result, context, source_guid)

    def process_batch(self, items: list[Any], context: ProcessingContext) -> list[ProcessingResult]:
        """
        Process multiple records.

        Handles exceptions gracefully - if one item fails, it creates a
        ProcessingResult.failed() for that item and continues processing
        remaining items.

        Args:
            items: List of input items
            context: Base ProcessingContext

        Returns:
            List of ProcessingResults (includes both successes and failures)
        """
        # CRITICAL: Capture start_time BEFORE firing start event (learned from TICKET-019 P0)
        start_time = datetime.now(timezone.utc)

        # Fire BP001: Batch processing started
        fire_event(
            BatchProcessingStartedEvent(
                agent_name=context.agent_name,
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

                # Track success/failure
                if result.status == ProcessingStatus.SUCCESS:
                    successes += 1
                elif result.status == ProcessingStatus.FAILED:
                    failures += 1

                # Fire BP002: Batch processing progress (every 10 records or at end)
                if (idx + 1) % 10 == 0 or (idx + 1) == len(items):
                    fire_event(
                        BatchProcessingProgressEvent(
                            agent_name=context.agent_name,
                            processed=idx + 1,
                            total=len(items),
                            successes=successes,
                            failures=failures,
                        )
                    )

            except ConfigurationError:
                # ConfigurationError indicates a fundamental workflow misconfiguration
                # Re-raise immediately to fail the workflow - these cannot be recovered
                raise
            except EmptyOutputError:
                # EmptyOutputError means on_empty=error was configured — user explicitly
                # wants the workflow to stop when an action produces empty output
                raise
            except TemplateVariableError as e:
                # TemplateVariableError indicates a code bug (undefined template variables)
                # Re-raise immediately to fail the workflow - these are not data errors
                fire_event(
                    TemplateRenderingFailedEvent(
                        agent_name=context.agent_name,
                        missing_variables=e.missing_variables,
                        error_message=str(e),
                    )
                )
                raise
            except SchemaValidationError:
                # SchemaValidationError means the output doesn't match the declared schema.
                # This is a systemic error — every record will fail the same way.
                raise
            except Exception as e:
                # Create failed result instead of propagating exception
                # This allows batch processing to continue for transient/data errors
                logger.exception(
                    "[%s] Error processing item %d: %s",
                    context.agent_name,
                    idx,
                    str(e),
                )
                # Preserve source_snapshot and source_guid for first-stage source saving
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

        # Fire BP003: Batch processing complete
        elapsed_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        fire_event(
            BatchProcessingCompleteEvent(
                agent_name=context.agent_name,
                total_records=len(items),
                elapsed_time=elapsed_time,
            )
        )

        return results

    # Private helper methods

    @staticmethod
    def _build_tombstone_item(
        content: Any,
        source_guid: Optional[str],
        reason: str,
        input_record: Optional[dict[str, Any]],
        *,
        extra_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Build a tombstone item for guard-skipped, exhausted, or unprocessed records.

        Args:
            content: Content to preserve in the tombstone
            source_guid: Source GUID for lineage
            reason: Reason string stored in metadata
            input_record: Original input record (for target_id preservation)
            extra_metadata: Additional metadata keys to merge (e.g. retry_exhausted)

        Returns:
            Tombstone dict ready for ProcessingResult.data
        """
        item: dict[str, Any] = {
            "content": content,
            "source_guid": source_guid,
            "metadata": {"reason": reason, "agent_type": "tombstone"},
            "_unprocessed": True,
        }
        if extra_metadata:
            item["metadata"].update(extra_metadata)
        if input_record and isinstance(input_record, dict) and "target_id" in input_record:
            item["target_id"] = input_record["target_id"]
        return item

    def _finalize_result(
        self,
        result: ProcessingResult,
        context: ProcessingContext,
        source_guid: Optional[str],
    ) -> ProcessingResult:
        """Enrich a result and fire the completion event.

        Centralises the enrich → fire-event → return pattern used by every
        non-filtered exit path in ``process()``.
        """
        enriched_result = self.enrichment_pipeline.enrich(result, context)
        fire_event(
            RecordProcessingCompleteEvent(
                agent_name=context.agent_name,
                record_index=context.record_index,
                source_guid=source_guid,
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
    ) -> list[dict[str, Any]]:
        """
        Transform LLM response to output format.

        Args:
            response: LLM response
            content: Original content
            source_guid: Source GUID
            passthrough_fields: Fields to pass through
            context: ProcessingContext

        Returns:
            List of transformed items
        """
        from agent_actions.processing.helpers import (
            transform_with_passthrough,
        )

        return transform_with_passthrough(
            response,
            content,
            source_guid,
            context.agent_config,
            action_name=context.action_name,
            passthrough_fields=passthrough_fields,
        )

    @staticmethod
    def _create_item_context(
        base_context: ProcessingContext, index: int, item: Any
    ) -> ProcessingContext:
        """
        Create per-item context with updated record_index.

        Args:
            base_context: Base ProcessingContext
            index: Item index
            item: Current item

        Returns:
            New ProcessingContext for this item
        """
        return replace(
            base_context,
            record_index=index,
            current_item=item if isinstance(item, dict) else None,
        )
