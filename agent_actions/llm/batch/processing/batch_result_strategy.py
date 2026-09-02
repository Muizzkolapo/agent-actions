"""Batch result processing strategy.

Converts raw BatchResult objects into enriched ProcessingResult records
that can flow through the shared enrich/collect pipeline.
"""

import copy
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_actions.processing.types import ProcessingContext

from agent_actions.errors import exhaustion_halt
from agent_actions.input.preprocessing.transformation.transformer import DataTransformer
from agent_actions.llm.batch.core.batch_constants import FilterStatus, OnExhaustedPolicy
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.response.config_fields import get_default
from agent_actions.processing.batch_context_adapter import BatchContextAdapter
from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.record_helpers import (
    build_exhausted_tombstone,
    build_tombstone,
    carry_framework_fields,
)
from agent_actions.processing.types import (
    ProcessingResult,
    ProcessingStatus,
    RecoveryMetadata,
    RetryMetadata,
)
from agent_actions.record.envelope import (
    _PERSISTENT_FIELDS,
    RecordEnvelope,
)
from agent_actions.record.reasons import (
    BATCH_NOT_RETURNED,
    GUARD_SKIP,
    PREP_FAILED,
)
from agent_actions.utils.content import get_existing_content, is_version_merge
from agent_actions.utils.schema_echo import is_schema_echo as _is_schema_echo
from agent_actions.utils.schema_echo import make_schema_echo_error as _make_schema_echo_error
from agent_actions.utils.transformation.passthrough import merge_passthrough_namespaces

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
    reconciler: BatchResultReconciler = None  # type: ignore[assignment]  # set by _init_context

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

    Implements ``ProcessingStrategy`` (via structural typing) so it can
    flow through ``UnifiedProcessor``.  Call ``prepare_invoke()`` to
    pre-load batch data before ``invoke()`` is called by the processor.
    """

    def __init__(self) -> None:
        self._pending_batch_results: list[BatchResult] | None = None
        self._pending_kwargs: dict[str, Any] = {}

    def prepare_invoke(
        self,
        batch_results: list[BatchResult],
        *,
        context_map: dict[str, Any] | None = None,
        output_directory: str | None = None,
        agent_config: dict[str, Any] | None = None,
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None,
    ) -> None:
        """Pre-load batch data for the next ``invoke()`` call.

        Must be called before ``UnifiedProcessor.process()`` or
        ``UnifiedProcessor.enrich_and_collect()`` invokes this strategy.
        """
        self._pending_batch_results = batch_results
        self._pending_kwargs = {
            "context_map": context_map,
            "output_directory": output_directory,
            "agent_config": agent_config,
            "exhausted_recovery": exhausted_recovery,
        }

    def invoke(
        self,
        records: list[dict[str, Any]],
        context: "ProcessingContext",
    ) -> list[ProcessingResult]:
        """ProcessingStrategy protocol: return results from pre-loaded batch data.

        The ``records`` parameter is accepted for protocol compliance but
        ignored — batch results are pre-loaded via ``prepare_invoke()``.
        Guard filtering already happened at batch submit time.
        """
        if self._pending_batch_results is None:
            raise RuntimeError("No batch data prepared. Call prepare_invoke() before invoke().")
        try:
            return self.process(self._pending_batch_results, **self._pending_kwargs)
        finally:
            self._pending_batch_results = None
            self._pending_kwargs = {}

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
        results: list[ProcessingResult] = []

        for batch_result in ctx.batch_results:
            custom_id = str(batch_result.custom_id)

            if BatchResultReconciler.is_answered(batch_result):
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
                recovery_metadata = batch_result.recovery_metadata
                exhausted = self._exhausted_recovery_for(ctx, custom_id)
                if exhausted is not None:
                    # Retry exhaustion is one half of the record's history; a
                    # reprompt or evaluation half may already be on it.
                    recovery_metadata = RecoveryMetadata(
                        retry=exhausted[1],
                        reprompt=recovery_metadata.reprompt if recovery_metadata else None,
                        evaluation=recovery_metadata.evaluation if recovery_metadata else None,
                    )

                results.append(
                    self._build_error_result(
                        ctx,
                        custom_id,
                        batch_result.error or "Batch processing failed",
                        batch_result.metadata,
                        recovery_metadata=recovery_metadata,
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
        generated_obj = batch_result.content
        if isinstance(generated_obj, str):
            if ctx.json_mode:
                # JSON mode but content is still a string — parsing failed.
                # Wrap in _parse_error dict so batch reprompt can detect and
                # retry, matching the online-path convention.
                logger.warning(
                    "Batch result for %s is unparsed string in json_mode; "
                    "wrapping as _parse_error for reprompt",
                    custom_id,
                )
                generated_obj = {
                    "raw_response": generated_obj,
                    "_parse_error": "Failed to parse JSON from LLM response",
                }
            else:
                generated_obj = {ctx.output_field: generated_obj}

        # Schema-echo guard: replace with _parse_error so reprompt can retry
        if _is_schema_echo(generated_obj):
            logger.warning(
                "[%s] Schema-echo detected in batch result — replacing with "
                "_parse_error for custom_id=%s.",
                ctx.agent_config.get("action_name", "unknown") if ctx.agent_config else "unknown",
                custom_id,
            )
            generated_obj = _make_schema_echo_error(generated_obj)

        generated_list = DataTransformer.ensure_list(generated_obj)

        original_row = ctx.reconciler.get_record_by_id(custom_id)
        original_source_guid = ctx.reconciler.get_source_guid(custom_id)

        stored_passthrough: dict[str, Any] = {}
        if ctx.agent_config:
            if custom_id in ctx.context_map:
                stored_passthrough = BatchContextMetadata.get_passthrough_fields(
                    ctx.context_map[custom_id]
                )
            elif (ctx.agent_config.get("context_scope") or {}).get("passthrough"):
                logger.warning(
                    "custom_id '%s' not found in context_map, skipping passthrough",
                    custom_id,
                )

        if not ctx.agent_config or "action_name" not in ctx.agent_config:
            raise ValueError("agent_config must contain 'action_name' for content namespacing")

        is_first_stage = not ctx.agent_config.get("dependencies")
        existing_content = get_existing_content(original_row, is_first_stage=is_first_stage)

        action_name = ctx.agent_config["action_name"]
        is_tool_version_merge = ctx.agent_config.get("kind") == "tool" and is_version_merge(
            ctx.agent_config
        )

        # Precompute persistent fields and envelope input outside the loop
        _vm_fields = tuple(f for f in _PERSISTENT_FIELDS if f != "source_guid")
        if not is_tool_version_merge:
            # Inject first-stage-aware content into the envelope input (matches online)
            if existing_content and existing_content != original_row.get("content"):
                envelope_input: dict[str, Any] = {**original_row, "content": existing_content}
            else:
                envelope_input = original_row

        structured_items = []
        for item in generated_list:
            item_dict = item if isinstance(item, dict) else {}
            if is_tool_version_merge:
                content = {**(existing_content or {}), **item_dict}
                record: dict[str, Any] = {"source_guid": original_source_guid, "content": content}
                carry_framework_fields(original_row, record, fields=_vm_fields)
            else:
                record = RecordEnvelope.build(action_name, item_dict, envelope_input)
                record["source_guid"] = original_source_guid  # reconciler is authority for guid
            if stored_passthrough:
                merge_passthrough_namespaces(record["content"], stored_passthrough, action_name)
            structured_items.append(record)

        # target_id is a per-stage field — not carried by RecordEnvelope.build()
        for item in structured_items:
            carry_framework_fields(original_row, item, fields=("target_id",))

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
        processing_result.is_expansion = len(structured_items) > 1
        return processing_result

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
        The ``data[0]`` dict contains ``error``, ``metadata``, and optionally
        ``raw_content`` and ``_recovery`` keys — this structure is load-bearing
        because ``write_record_dispositions()`` iterates ``data`` items and
        checks ``item.get("error")`` to detect failures.

        This differs from the online/file_tool paths where errors are only on
        ``result.error`` with ``result.data == []``.  The dual representation
        exists because batch post-processing (disposition writing) needs
        per-item error context while online errors are handled at the
        result-status level in ``collect_results()``.

        Error results are NOT enriched (matching the original pipeline behaviour).
        """
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

        original_input = ctx.reconciler.get_record_by_id(custom_id)
        source_snapshot = copy.deepcopy(original_input) if original_input else None

        result = ProcessingResult.failed(
            error=error_message,
            source_guid=source_guid,
            source_snapshot=source_snapshot,
            input_record=original_input,
        )
        result.data = [error_item]
        result.recovery_metadata = recovery_metadata
        return result

    def _exhausted_recovery_for(
        self, ctx: BatchProcessingContext, custom_id: str
    ) -> tuple[RecoveryMetadata, RetryMetadata] | None:
        """Retry-exhaustion metadata for *custom_id*, or None if it still has attempts.

        Applies ``on_exhausted`` here so the policy reaches every record that
        spent its attempts, including one the provider answered with an error
        and therefore left a result behind for.
        """
        if not ctx.exhausted_recovery or custom_id not in ctx.exhausted_recovery:
            return None

        recovery_meta = ctx.exhausted_recovery[custom_id]
        retry_meta = recovery_meta.retry
        if retry_meta is None:
            raise RuntimeError(
                "RecoveryMetadata.retry is None for exhausted record "
                f"custom_id={custom_id}; expected retry metadata with attempt count"
            )

        on_exhausted = OnExhaustedPolicy.RETURN_LAST
        if ctx.agent_config:
            retry_config = ctx.agent_config.get("retry") or {}
            on_exhausted = OnExhaustedPolicy(retry_config.get("on_exhausted") or "return_last")

        if on_exhausted == OnExhaustedPolicy.RAISE:
            raise exhaustion_halt(
                f"Retry exhausted for record {custom_id} after "
                f"{retry_meta.attempts} attempts (on_exhausted=raise)"
            )

        return recovery_meta, retry_meta

    # -- Passthrough reconciliation --------------------------------------------

    def _reconcile_passthroughs(self, ctx: BatchProcessingContext) -> list[ProcessingResult]:
        """Reconcile missing/skipped records into ProcessingResult objects.

        Routes exhausted-retry and passthrough records through enrichment
        for consistent lineage, metadata, and version_correlation_id.
        """
        reconciliation = ctx.reconciler.reconcile()
        results: list[ProcessingResult] = []

        if not reconciliation.passthrough_records:
            return results

        for custom_id, original_row in reconciliation.passthrough_records:
            is_exhausted = ctx.exhausted_recovery and custom_id in ctx.exhausted_recovery
            is_failed = BatchContextMetadata.get_filter_status(original_row) == FilterStatus.FAILED

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
            elif is_failed:
                result = self._build_failed_passthrough(
                    ctx,
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

    def _attach_passthrough_context(
        self,
        result: ProcessingResult,
        ctx: BatchProcessingContext,
        original_row: dict[str, Any],
        record_index: int,
    ) -> None:
        """Attach processing context to a passthrough result."""
        result.processing_context = BatchContextAdapter.to_processing_context(
            agent_config=ctx.agent_config or {},
            original_row=original_row,
            record_index=record_index,
            output_directory=ctx.output_directory,
        )

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
        exhausted = self._exhausted_recovery_for(ctx, custom_id)
        if exhausted is None:
            raise RuntimeError(
                "BatchProcessingContext.exhausted_recovery is None "
                "but record was identified as exhausted; "
                f"expected exhausted_recovery dict for custom_id={custom_id}"
            )
        recovery_meta, retry_meta = exhausted

        empty_content = ExhaustedRecordBuilder.build_empty_content(ctx.agent_config or {})
        exhausted_item = build_exhausted_tombstone(
            action_name,
            original_row,
            empty_content,
            source_guid=source_guid,
        )

        processing_result = ProcessingResult.exhausted(
            error=f"Retry exhausted after {retry_meta.attempts} attempts",
            data=[exhausted_item],
            source_guid=source_guid,
            recovery_metadata=recovery_meta,
            source_snapshot=copy.deepcopy(original_row) if original_row else None,
        )
        self._attach_passthrough_context(processing_result, ctx, original_row, record_index)
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
        # Single authority: skip_reason set during preparation is canonical.
        skip_reason = BatchContextMetadata.get_skip_reason(original_row)
        if skip_reason:
            reason = skip_reason
        elif BatchContextMetadata.get_filter_status(original_row) == FilterStatus.SKIPPED:
            reason = GUARD_SKIP
        else:
            reason = BATCH_NOT_RETURNED

        passthrough_item = build_tombstone(
            action_name,
            original_row,
            reason,
            source_guid=source_guid,
        )

        processing_result = ProcessingResult.unprocessed(
            data=[passthrough_item],
            reason=reason,
            source_guid=source_guid,
            source_snapshot=copy.deepcopy(original_row) if original_row else None,
        )
        self._attach_passthrough_context(processing_result, ctx, original_row, record_index)
        return processing_result

    def _build_failed_passthrough(
        self,
        ctx: BatchProcessingContext,
        original_row: dict[str, Any],
        action_name: str,
        source_guid: str,
        record_index: int,
    ) -> ProcessingResult:
        """Build a FAILED result for a record that failed during batch preparation.

        Records with FilterStatus.FAILED were never submitted to the provider.
        They must still appear in output so downstream consumers see all records.
        """
        skip_reason = BatchContextMetadata.get_skip_reason(original_row)
        reason = skip_reason or PREP_FAILED

        passthrough_item = build_tombstone(
            action_name,
            original_row,
            reason,
            source_guid=source_guid,
        )

        processing_result = ProcessingResult.failed(
            error=reason,
            source_guid=source_guid,
            source_snapshot=copy.deepcopy(original_row) if original_row else None,
        )
        processing_result.data = [passthrough_item]
        self._attach_passthrough_context(processing_result, ctx, original_row, record_index)
        processing_result.skip_reason = reason
        return processing_result
