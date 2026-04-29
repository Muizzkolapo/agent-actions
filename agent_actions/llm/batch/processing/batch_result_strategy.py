"""Batch result processing strategy.

Converts raw BatchResult objects into enriched ProcessingResult records
that can flow through the shared enrich/collect pipeline.
"""

import logging
from dataclasses import dataclass
from typing import Any

from agent_actions.input.preprocessing.transformation.transformer import DataTransformer
from agent_actions.llm.batch.core.batch_constants import ContextMetaKeys, FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.response.config_fields import get_default
from agent_actions.processing.batch_context_adapter import BatchContextAdapter
from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.record_helpers import (
    apply_version_merge,
    build_cascade_skipped_record,
    build_exhausted_tombstone,
    build_failed_record,
    build_guard_skipped_record,
    carry_framework_fields,
)
from agent_actions.processing.types import (
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
)
from agent_actions.utils.content import get_existing_content

logger = logging.getLogger(__name__)


@dataclass
class BatchProcessingContext:
    """Internal context for batch result parsing."""

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


class BatchResultStrategy:
    """Converts batch provider results into ProcessingResult objects.

    Unlike InvocationStrategy implementations that invoke LLM/tool/HITL,
    this processes already-returned batch results.  The ``process()`` method
    returns ``list[ProcessingResult]`` so the caller can flatten, collect,
    and write dispositions through the shared pipeline.

    Each returned result carries a ``processing_context`` field that the
    caller (``BatchProcessingService``) uses to run enrichment through the
    shared enrichment pipeline.  Error results have ``processing_context``
    set to ``None`` and are intentionally not enriched.
    """

    def process(
        self,
        batch_results: list[BatchResult],
        context_map: dict[str, Any] | None = None,
        output_directory: str | None = None,
        agent_config: dict[str, Any] | None = None,
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    ) -> list[ProcessingResult]:
        """Convert batch results into unenriched ProcessingResult objects.

        Returns one ProcessingResult per input record (successful, failed,
        exhausted, or unprocessed).  Successful, exhausted, and unprocessed
        results carry a ``processing_context`` field; the caller uses it to
        run enrichment through the shared enrichment pipeline.  Error
        results have ``processing_context=None`` and are not enriched.

        The caller is responsible for enriching, flattening ``result.data``
        into output records, and writing dispositions.
        """
        ctx = self._init_context(
            batch_results,
            context_map,
            output_directory,
            agent_config,
            exhausted_recovery,
        )
        ctx.reconciler = BatchResultReconciler(ctx.context_map)

        results = self._process_batch_results(ctx)
        results.extend(self._reconcile_passthroughs(ctx))

        success_count = sum(1 for r in results if r.status == ProcessingStatus.SUCCESS)
        error_count = sum(
            1 for r in results if r.status in (ProcessingStatus.FAILED, ProcessingStatus.EXHAUSTED)
        )
        passthrough_count = sum(1 for r in results if r.status == ProcessingStatus.UNPROCESSED)

        logger.debug(
            "Batch result processing complete: %d success, %d errors, %d passthrough",
            success_count,
            error_count,
            passthrough_count,
        )

        return results

    # -- Initialisation --------------------------------------------------------

    def _init_context(
        self,
        batch_results: list[BatchResult],
        context_map: dict[str, Any] | None,
        output_directory: str | None,
        agent_config: dict[str, Any] | None,
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    ) -> BatchProcessingContext:
        """Build the internal parsing context from caller parameters."""
        context_map = context_map or {}

        json_mode = get_default("json_mode")
        output_field = get_default("output_field")
        if agent_config:
            json_mode = agent_config.get("json_mode", json_mode)
            output_field = agent_config.get("output_field", output_field)

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

    # -- Batch result processing -----------------------------------------------

    def _process_batch_results(self, ctx: BatchProcessingContext) -> list[ProcessingResult]:
        """Process all batch results, returning one ProcessingResult per result."""
        if ctx.reconciler is None:
            raise RuntimeError(
                "BatchProcessingContext.reconciler is None; "
                "reconciler must be initialized before processing results"
            )
        results: list[ProcessingResult] = []

        for batch_result in ctx.batch_results:
            custom_id = str(batch_result.custom_id)

            if batch_result.success and batch_result.content is not None:
                try:
                    result = self._process_successful_result(ctx, batch_result, custom_id)
                    results.append(result)
                    ctx.reconciler.mark_processed(custom_id)

                    logger.debug(
                        "Processed batch result item",
                        extra={
                            "operation": "process_batch_item",
                            "custom_id": custom_id,
                            "items_generated": len(result.data),
                            "success": True,
                        },
                    )

                except Exception as e:
                    results.append(
                        self._build_error_result(
                            ctx,
                            custom_id,
                            f"Processing error: {str(e)}",
                            batch_result.metadata,
                            batch_result.content,
                            recovery_metadata=batch_result.recovery_metadata,
                        )
                    )
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
                results.append(
                    self._build_error_result(
                        ctx,
                        custom_id,
                        batch_result.error or "Batch processing failed",
                        batch_result.metadata,
                        recovery_metadata=batch_result.recovery_metadata,
                    )
                )
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

        return results

    def _process_successful_result(
        self,
        ctx: BatchProcessingContext,
        batch_result: BatchResult,
        custom_id: str,
    ) -> ProcessingResult:
        """Parse a successful batch result into a ProcessingResult."""
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
                generated_list = self._apply_context_passthrough(ctx, custom_id, generated_list)
            elif ctx.agent_config.get("context_scope", {}).get("passthrough"):
                logger.warning(
                    "custom_id '%s' not found in context_map, skipping passthrough",
                    custom_id,
                )

        if not ctx.agent_config or "action_name" not in ctx.agent_config:
            raise ValueError("agent_config must contain 'action_name' for content namespacing")

        existing_content = get_existing_content(original_row)

        structured_items = []
        for item in generated_list:
            item_dict = item if isinstance(item, dict) else {}
            content = apply_version_merge(ctx.agent_config, item_dict, existing_content)
            structured_items.append({"source_guid": original_source_guid, "content": content})

        # Batch items inherit target_id and version_correlation_id from the original input row.
        for item in structured_items:
            carry_framework_fields(
                original_row, item, fields=("target_id", "version_correlation_id")
            )

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

        processing_result.processing_context = processing_context
        return processing_result

    def _apply_context_passthrough(
        self,
        ctx: BatchProcessingContext,
        custom_id: str,
        generated_list: list[Any],
    ) -> list[Any]:
        """Apply stored context_scope.passthrough fields to generated items."""
        stored_passthrough = BatchContextMetadata.get_passthrough_fields(ctx.context_map[custom_id])

        if stored_passthrough:
            generated_list = [
                {**item, **stored_passthrough} if isinstance(item, dict) else item
                for item in generated_list
            ]

        return generated_list

    # -- Error / exhausted / unprocessed builders ------------------------------

    def _build_error_result(
        self,
        ctx: BatchProcessingContext,
        custom_id: str,
        error_message: str,
        metadata: dict[str, Any] | None = None,
        raw_content: Any = None,
        recovery_metadata: RecoveryMetadata | None = None,
    ) -> ProcessingResult:
        """Build a FAILED ProcessingResult for a batch error.

        Error results carry the error dict in ``data`` so that downstream
        ``write_record_dispositions()`` can still find and disposition them.
        Error results are NOT enriched (matching the original pipeline behaviour).
        """
        if ctx.reconciler is None:
            raise RuntimeError(
                "BatchProcessingContext.reconciler is None; "
                "reconciler must be initialized before creating error items"
            )
        source_guid = ctx.reconciler.get_source_guid(custom_id, fallback=custom_id or "NOT_SET")

        error_item: dict[str, Any] = {
            "source_guid": source_guid,
            "error": error_message,
            "metadata": metadata or {},
        }

        if raw_content is not None:
            error_item["raw_content"] = raw_content

        if recovery_metadata:
            error_item["_recovery"] = recovery_metadata.to_dict()

        return ProcessingResult(
            status=ProcessingStatus.FAILED,
            data=[error_item],
            source_guid=source_guid,
            error=error_message,
            recovery_metadata=recovery_metadata,
        )

    # -- Passthrough reconciliation --------------------------------------------

    def _reconcile_passthroughs(self, ctx: BatchProcessingContext) -> list[ProcessingResult]:
        """Reconcile missing/skipped records into ProcessingResult objects.

        Routes exhausted-retry and passthrough records through enrichment
        for consistent lineage, metadata, and version_correlation_id.
        """
        if ctx.reconciler is None:
            raise RuntimeError(
                "BatchProcessingContext.reconciler is None; "
                "reconciler must be initialized before merging passthroughs"
            )
        reconciliation = ctx.reconciler.reconcile()
        results: list[ProcessingResult] = []

        if not reconciliation.passthrough_records:
            return results

        for custom_id, original_row in reconciliation.passthrough_records:
            is_exhausted = ctx.exhausted_recovery and custom_id in ctx.exhausted_recovery

            record_index = ctx.reconciler.get_record_index(custom_id)
            source_guid = ctx.reconciler.get_source_guid(custom_id, fallback=custom_id or "NOT_SET")

            if not ctx.agent_config or "action_name" not in ctx.agent_config:
                raise ValueError("agent_config must contain 'action_name' for content namespacing")
            action_name = ctx.agent_config["action_name"]

            if is_exhausted:
                result = self._build_exhausted_passthrough(
                    ctx,
                    custom_id,
                    original_row,
                    action_name,
                    source_guid,
                    record_index,
                )
            else:
                result = self._build_unprocessed_passthrough(
                    ctx,
                    original_row,
                    action_name,
                    source_guid,
                    record_index,
                )
            results.append(result)

        return results

    def _build_exhausted_passthrough(
        self,
        ctx: BatchProcessingContext,
        custom_id: str,
        original_row: dict[str, Any],
        action_name: str,
        source_guid: str,
        record_index: int,
    ) -> ProcessingResult:
        """Build an EXHAUSTED result for a retry-exhausted record."""
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

        recovery_meta = ctx.exhausted_recovery[custom_id]
        if recovery_meta.retry is None:
            raise RuntimeError(
                "RecoveryMetadata.retry is None for exhausted record "
                f"custom_id={custom_id}; expected retry metadata with attempt count"
            )

        if on_exhausted == "raise":
            raise RuntimeError(
                f"Retry exhausted for record {custom_id} after "
                f"{recovery_meta.retry.attempts} attempts (on_exhausted=raise)"
            )
        empty_content = ExhaustedRecordBuilder.build_empty_content(ctx.agent_config or {})
        exhausted_item = build_exhausted_tombstone(
            action_name,
            original_row,
            empty_content,
            source_guid=source_guid,
        )

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
        processing_result.processing_context = processing_context
        return processing_result

    def _build_unprocessed_passthrough(
        self,
        ctx: BatchProcessingContext,
        original_row: dict[str, Any],
        action_name: str,
        source_guid: str,
        record_index: int,
    ) -> ProcessingResult:
        """Build an UNPROCESSED result for a passthrough record."""
        # Determine actual skip reason from context metadata
        filter_phase = original_row.get(ContextMetaKeys.FILTER_PHASE, "")
        if filter_phase == "upstream_unprocessed":
            passthrough_item = build_cascade_skipped_record(
                action_name,
                original_row,
                source_guid=source_guid,
                upstream_action="unknown",
                upstream_state="unprocessed",
            )
            reason = "cascade_skipped"
        elif BatchContextMetadata.get_filter_status(original_row) == FilterStatus.SKIPPED:
            passthrough_item = build_guard_skipped_record(
                action_name,
                original_row,
                source_guid=source_guid,
                clause=str(ctx.agent_config.get("guard", {}).get("clause", "")) if ctx.agent_config else "",
                behavior="skip",
                result=False,
            )
            reason = "guard_skipped"
        else:
            passthrough_item = build_failed_record(
                action_name,
                original_row,
                source_guid=source_guid,
                error_type="batch_not_returned",
                message="Batch API did not return a record for this custom_id",
            )
            reason = "failed"

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
        processing_result.processing_context = processing_context
        return processing_result
