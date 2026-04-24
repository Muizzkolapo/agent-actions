"""
Batch Result Processor.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_actions.input.preprocessing.transformation.transformer import DataTransformer
from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.response.config_fields import get_default
from agent_actions.processing.batch_context_adapter import BatchContextAdapter
from agent_actions.processing.enrichment import EnrichmentPipeline
from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.types import ProcessingResult, RecoveryMetadata
from agent_actions.record.envelope import RecordEnvelope

logger = logging.getLogger(__name__)


@dataclass
class BatchProcessingContext:
    """Context passed through the batch result processing pipeline."""

    # Input data
    batch_results: list[BatchResult]
    context_map: dict[str, Any]
    output_directory: str | None
    agent_config: dict[str, Any] | None

    # Extracted configuration — defaults match SIMPLE_CONFIG_FIELDS (single source of truth)
    json_mode: bool = True
    output_field: str = "raw_response"

    # Reconciliation
    reconciler: BatchResultReconciler | None = None

    # Per-record recovery metadata for exhausted records (custom_id -> RecoveryMetadata)
    exhausted_recovery: dict[str, RecoveryMetadata] | None = None

    # Accumulated output
    processed_data: list[dict[str, Any]] = field(default_factory=list)

    # Statistics
    success_count: int = 0
    error_count: int = 0
    passthrough_count: int = 0


class BatchResultProcessor:
    """Converts batch provider results into workflow format via pipeline stages."""

    def __init__(self):
        self._enrichment_pipeline = EnrichmentPipeline()

    def process(
        self,
        batch_results: list[BatchResult],
        context_map: dict[str, Any] | None = None,
        output_directory: str | None = None,
        agent_config: dict[str, Any] | None = None,
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    ) -> list[dict[str, Any]]:
        """Process batch results through the pipeline into workflow format."""
        ctx = self._stage_1_initialize_context(
            batch_results,
            context_map,
            output_directory,
            agent_config,
            exhausted_recovery,
        )

        ctx = self._stage_2_reconcile(ctx)

        ctx = self._stage_3_4_process_results(ctx)

        ctx = self._stage_6_merge_passthroughs(ctx)

        logger.debug(
            "Batch result processing complete: %d success, %d errors, %d passthrough",
            ctx.success_count,
            ctx.error_count,
            ctx.passthrough_count,
        )

        return ctx.processed_data

    def _stage_1_initialize_context(
        self,
        batch_results: list[BatchResult],
        context_map: dict[str, Any] | None,
        output_directory: str | None,
        agent_config: dict[str, Any] | None,
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    ) -> BatchProcessingContext:
        """Initialize processing context with configuration values."""
        context_map = context_map or {}

        json_mode = get_default("json_mode")
        output_field = get_default("output_field")
        if agent_config:
            json_mode = agent_config.get("json_mode", get_default("json_mode"))
            output_field = agent_config.get("output_field", get_default("output_field"))

        ctx = BatchProcessingContext(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
            json_mode=json_mode,
            output_field=output_field,
            exhausted_recovery=exhausted_recovery,
        )

        logger.debug(
            "Initialized processing context: %d batch results, %d context records",
            len(batch_results),
            len(context_map),
        )

        return ctx

    def _stage_2_reconcile(self, ctx: BatchProcessingContext) -> BatchProcessingContext:
        """Set up BatchResultReconciler for tracking processed vs missing records."""
        ctx.reconciler = BatchResultReconciler(ctx.context_map)
        return ctx

    def _stage_3_4_process_results(self, ctx: BatchProcessingContext) -> BatchProcessingContext:
        """Process all batch results, handling both successes and errors."""
        if ctx.reconciler is None:
            raise RuntimeError(
                "BatchProcessingContext.reconciler is None; "
                "_stage_2_reconcile() must run before _stage_3_4_process_results()"
            )
        for batch_result in ctx.batch_results:
            custom_id = str(batch_result.custom_id)

            if batch_result.success and batch_result.content is not None:
                try:
                    items = self._process_successful_result(ctx, batch_result, custom_id)
                    ctx.processed_data.extend(items)
                    ctx.success_count += len(items)
                    ctx.reconciler.mark_processed(custom_id)

                    logger.debug(
                        "Processed batch result item",
                        extra={
                            "operation": "process_batch_item",
                            "custom_id": custom_id,
                            "items_generated": len(items),
                            "success": True,
                        },
                    )

                except Exception as e:
                    error_item = self._create_error_item(
                        ctx,
                        custom_id,
                        f"Processing error: {str(e)}",
                        batch_result.metadata,
                        batch_result.content,
                        recovery_metadata=batch_result.recovery_metadata,
                    )
                    ctx.processed_data.append(error_item)
                    ctx.error_count += 1
                    ctx.reconciler.mark_processed(custom_id)

                    logger.error(
                        "Batch result item processing failed",
                        extra={
                            "operation": "process_batch_item",
                            "custom_id": custom_id,
                            "success": False,
                            "error": str(e),
                        },
                    )

            else:
                error_item = self._create_error_item(
                    ctx,
                    custom_id,
                    batch_result.error or "Batch processing failed",
                    batch_result.metadata,
                    recovery_metadata=batch_result.recovery_metadata,
                )
                ctx.processed_data.append(error_item)
                ctx.error_count += 1
                ctx.reconciler.mark_processed(custom_id)

                logger.error(
                    "Batch result item had error",
                    extra={
                        "operation": "process_batch_item",
                        "custom_id": custom_id,
                        "success": False,
                        "error": batch_result.error or "Batch processing failed",
                    },
                )

        return ctx

    def _process_successful_result(
        self, ctx: BatchProcessingContext, batch_result: BatchResult, custom_id: str
    ) -> list[dict[str, Any]]:
        """Build agent output from successful batch result, delegating enrichment to EnrichmentPipeline."""
        if ctx.reconciler is None:
            raise RuntimeError(
                "BatchProcessingContext.reconciler is None; "
                "reconciler must be initialized before processing results"
            )
        generated_obj = batch_result.content
        if not ctx.json_mode and isinstance(generated_obj, str):
            generated_obj = {ctx.output_field: generated_obj}

        generated_list = DataTransformer.ensure_list(generated_obj)

        original_row = ctx.reconciler.get_record_by_id(custom_id)
        original_source_guid = ctx.reconciler.get_source_guid(custom_id)

        if ctx.agent_config:
            if custom_id in ctx.context_map:
                generated_list = self._apply_context_passthrough(
                    ctx, custom_id, generated_list, original_row
                )
            elif ctx.agent_config.get("context_scope", {}).get("passthrough"):
                # Passthrough configured but custom_id missing from context_map
                logger.warning(
                    "custom_id '%s' not found in context_map, skipping passthrough",
                    custom_id,
                )

        if not ctx.agent_config or "action_name" not in ctx.agent_config:
            raise ValueError("agent_config must contain 'action_name' for content namespacing")
        from agent_actions.utils.content import is_version_merge

        action_name = ctx.agent_config["action_name"]
        version_merge = is_version_merge(ctx.agent_config)
        existing = original_row.get("content") if isinstance(original_row, dict) else None
        existing_content = existing if isinstance(existing, dict) else None

        structured_items = []
        for item in generated_list:
            item_dict = item if isinstance(item, dict) else {}
            if version_merge:
                content = {**(existing_content or {}), **item_dict}
            else:
                content = RecordEnvelope.build_content(action_name, item_dict, existing_content)
            structured_items.append({"source_guid": original_source_guid, "content": content})

        # Batch items inherit target_id from the original input row.
        # transform_structure() doesn't carry it over, so set it before enrichment.
        original_target_id = original_row.get("target_id")
        if original_target_id:
            for item in structured_items:
                if "target_id" not in item or not item["target_id"]:
                    item["target_id"] = original_target_id

        record_index = ctx.reconciler.get_record_index(custom_id)

        processing_context = BatchContextAdapter.to_processing_context(
            agent_config=ctx.agent_config or {},
            original_row=original_row,
            record_index=record_index,
            output_directory=ctx.output_directory,
        )

        processing_result = BatchContextAdapter.to_processing_result(
            data=structured_items,
            source_guid=original_source_guid,
            pre_extracted_metadata=batch_result.metadata,
            recovery_metadata=batch_result.recovery_metadata,
        )

        enriched = self._enrichment_pipeline.enrich(processing_result, processing_context)

        return enriched.data

    def _apply_context_passthrough(
        self,
        ctx: BatchProcessingContext,
        custom_id: str,
        generated_list: list[Any],
        original_row: dict[str, Any],
    ) -> list[Any]:
        """Apply context_scope.passthrough fields to generated items."""
        stored_passthrough = BatchContextMetadata.get_passthrough_fields(ctx.context_map[custom_id])

        if stored_passthrough:
            from agent_actions.prompt.context.scope_application import merge_passthrough_fields

            generated_list = merge_passthrough_fields(generated_list, stored_passthrough)

        elif ctx.agent_config and ctx.agent_config.get("context_scope", {}).get("passthrough"):
            passthrough_refs = ctx.agent_config.get("context_scope", {}).get("passthrough", [])
            passthrough_fields = []

            for field_ref in passthrough_refs:
                try:
                    from agent_actions.prompt.context.scope_parsing import parse_field_reference

                    _, field_name = parse_field_reference(field_ref)
                    passthrough_fields.append(field_name)
                except ValueError:
                    # If parsing fails, use the whole string as field name
                    passthrough_fields.append(field_ref)

            original_content = original_row.get("content", original_row)

            generated_list = [
                (
                    DataTransformer.update_schema_objects(
                        original_content, item, passthrough_fields
                    )
                    if isinstance(item, dict)
                    else item
                )
                for item in generated_list
            ]

        return generated_list

    def _create_error_item(
        self,
        ctx: BatchProcessingContext,
        custom_id: str,
        error_message: str,
        metadata: dict[str, Any] | None = None,
        raw_content: Any = None,
        recovery_metadata: RecoveryMetadata | None = None,
    ) -> dict[str, Any]:
        """Create an error item for failed batch results."""
        if ctx.reconciler is None:
            raise RuntimeError(
                "BatchProcessingContext.reconciler is None; "
                "reconciler must be initialized before creating error items"
            )
        source_guid = ctx.reconciler.get_source_guid(custom_id, fallback=custom_id or "unknown")

        error_item: dict[str, Any] = {
            "source_guid": source_guid,
            "error": error_message,
            "metadata": metadata or {},
        }

        if raw_content is not None:
            error_item["raw_content"] = raw_content

        if recovery_metadata:
            error_item["_recovery"] = recovery_metadata.to_dict()

        return error_item

    def _create_exhausted_item(
        self,
        ctx: BatchProcessingContext,
        custom_id: str,
        original_row: dict[str, Any],
        recovery_metadata: RecoveryMetadata,
    ) -> dict[str, Any]:
        """Create an exhausted retry item via ExhaustedRecordBuilder."""
        if ctx.reconciler is None:
            raise RuntimeError(
                "BatchProcessingContext.reconciler is None; "
                "reconciler must be initialized before creating exhausted items"
            )
        from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder

        source_guid = ctx.reconciler.get_source_guid(custom_id, fallback=custom_id or "unknown")

        return ExhaustedRecordBuilder.build_exhausted_item(
            source_guid=source_guid,
            original_row=original_row,
            recovery_metadata=recovery_metadata,
            agent_config=ctx.agent_config or {},
            action_name=ctx.agent_config.get("action_name", "") if ctx.agent_config else "",
        )

    def _stage_6_merge_passthroughs(self, ctx: BatchProcessingContext) -> BatchProcessingContext:
        """
        Stage 6: Merge passthrough records for missing/skipped items.

        Routes all passthrough/exhausted records through the EnrichmentPipeline
        for consistent lineage, metadata, and version_correlation_id enrichment.

        IMPORTANT: Exhausted retry records are treated differently from skipped records:
        - Skipped records (guard/conditional): Passthrough with original content
        - Exhausted retry records: Empty schema content + _recovery metadata
        """
        if ctx.reconciler is None:
            raise RuntimeError(
                "BatchProcessingContext.reconciler is None; "
                "reconciler must be initialized before merging passthroughs"
            )
        reconciliation = ctx.reconciler.reconcile()

        if reconciliation.passthrough_records:
            for custom_id, original_row in reconciliation.passthrough_records:
                is_exhausted = ctx.exhausted_recovery and custom_id in ctx.exhausted_recovery

                record_index = ctx.reconciler.get_record_index(custom_id)
                source_guid = ctx.reconciler.get_source_guid(
                    custom_id, fallback=custom_id or "unknown"
                )

                if is_exhausted:
                    if ctx.exhausted_recovery is None:
                        raise RuntimeError(
                            "BatchProcessingContext.exhausted_recovery is None "
                            "but record was identified as exhausted; "
                            f"expected exhausted_recovery dict for custom_id={custom_id}"
                        )
                    on_exhausted = "return_last"  # default
                    if ctx.agent_config:
                        retry_config = ctx.agent_config.get("retry", {})
                        on_exhausted = retry_config.get("on_exhausted", "return_last")

                    if on_exhausted == "raise":
                        recovery_meta = ctx.exhausted_recovery[custom_id]
                        if recovery_meta.retry is None:
                            raise RuntimeError(
                                "RecoveryMetadata.retry is None for exhausted record "
                                f"custom_id={custom_id}; expected retry metadata"
                            )
                        raise RuntimeError(
                            f"Retry exhausted for record {custom_id} after "
                            f"{recovery_meta.retry.attempts} attempts (on_exhausted=raise)"
                        )

                    recovery_meta = ctx.exhausted_recovery[custom_id]
                    if recovery_meta.retry is None:
                        raise RuntimeError(
                            "RecoveryMetadata.retry is None for exhausted record "
                            f"custom_id={custom_id}; expected retry metadata with attempt count"
                        )
                    from agent_actions.utils.content import get_existing_content

                    empty_content = ExhaustedRecordBuilder.build_empty_content(
                        ctx.agent_config or {}
                    )
                    existing = get_existing_content(original_row)
                    if not ctx.agent_config or "action_name" not in ctx.agent_config:
                        raise ValueError(
                            "agent_config must contain 'action_name' for content namespacing"
                        )
                    stage6_action_name = ctx.agent_config["action_name"]
                    exhausted_item = {
                        "content": RecordEnvelope.build_content(
                            stage6_action_name, empty_content, existing
                        ),
                        "source_guid": source_guid,
                        "metadata": {"retry_exhausted": True, "agent_type": "tombstone"},
                        "_unprocessed": True,
                    }
                    if original_row.get("target_id"):
                        exhausted_item["target_id"] = original_row["target_id"]

                    processing_context = BatchContextAdapter.to_processing_context(
                        agent_config=ctx.agent_config or {},
                        original_row=original_row,
                        record_index=record_index,
                        output_directory=ctx.output_directory,
                    )
                    processing_result = ProcessingResult.exhausted(
                        error=f"Retry exhausted after {recovery_meta.retry.attempts} attempts",
                        data=[exhausted_item],
                        source_guid=source_guid,
                        recovery_metadata=recovery_meta,
                    )
                    enriched = self._enrichment_pipeline.enrich(
                        processing_result, processing_context
                    )
                    ctx.processed_data.extend(enriched.data)
                    ctx.error_count += 1
                else:
                    # Determine actual skip reason from context metadata
                    filter_phase = original_row.get(ContextMetaKeys.FILTER_PHASE, "")
                    if filter_phase == "upstream_unprocessed":
                        reason = "upstream_unprocessed"
                    elif (
                        BatchContextMetadata.get_filter_status(original_row) == FilterStatus.SKIPPED
                    ):
                        reason = "guard_skipped"
                    else:
                        reason = "batch_not_returned"

                    if not ctx.agent_config or "action_name" not in ctx.agent_config:
                        raise ValueError(
                            "agent_config must contain 'action_name' for content namespacing"
                        )
                    passthrough_action_name = ctx.agent_config["action_name"]
                    passthrough_item = RecordEnvelope.build_skipped(
                        passthrough_action_name, original_row
                    )
                    passthrough_item["source_guid"] = source_guid
                    passthrough_item["metadata"] = {
                        "reason": reason,
                        "agent_type": "tombstone",
                    }
                    passthrough_item["_unprocessed"] = True
                    if original_row.get("target_id"):
                        passthrough_item["target_id"] = original_row["target_id"]

                    processing_context = BatchContextAdapter.to_processing_context(
                        agent_config=ctx.agent_config or {},
                        original_row=original_row,
                        record_index=record_index,
                        output_directory=ctx.output_directory,
                    )
                    processing_result = ProcessingResult.unprocessed(
                        data=[passthrough_item],
                        reason=reason,
                        source_guid=source_guid,
                    )
                    enriched = self._enrichment_pipeline.enrich(
                        processing_result, processing_context
                    )
                    ctx.processed_data.extend(enriched.data)
                    ctx.passthrough_count += 1

        return ctx
