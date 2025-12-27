"""
Batch Result Processor.

Pipeline-based processor for converting batch provider results to workflow format.
Replaces the complex _convert_batch_results_to_workflow_format method with a clean,
testable pipeline architecture.
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from agent_actions.preprocessing.transformation.data_transformer import DataTransformer
from agent_actions.utilities.id_generation import IDGenerator
from agent_actions.utilities.lineage import LineageBuilder
from agent_actions.utilities.correlation import LoopIdGenerator
from agent_actions.llm_invocation.batch.batch_result_reconciler import BatchResultReconciler
from agent_actions.llm_invocation.batch.batch_passthrough_builder import BatchPassthroughBuilder
from agent_actions.llm_invocation.providers.batch_client_base import BatchResult

logger = logging.getLogger(__name__)


@dataclass
class BatchProcessingContext:  # pylint: disable=too-many-instance-attributes
    """
    Context passed through the processing pipeline.

    Contains all data needed for processing batch results, accumulated
    across pipeline stages.
    """

    # Input data
    batch_results: List[BatchResult]
    context_map: Dict[str, Any]
    output_directory: Optional[str]
    agent_config: Optional[Dict[str, Any]]

    # Extracted configuration
    node_idx: Optional[int] = None
    json_mode: bool = True
    output_field: str = "content"

    # Reconciliation
    reconciler: Optional[BatchResultReconciler] = None

    # Accumulated output
    processed_data: List[Dict[str, Any]] = field(default_factory=list)

    # Statistics
    success_count: int = 0
    error_count: int = 0
    passthrough_count: int = 0


class BatchResultProcessor:  # pylint: disable=too-few-public-methods
    """
    Pipeline-based processor for batch results.

    Converts batch provider results into workflow format using a clean
    9-stage pipeline architecture. Each stage has a single responsibility
    and can be tested independently.

    Pipeline stages:
    1. Initialize context
    2. Reconcile requests/responses
    3. Process successful results
    4. Process error results
    5. Build agent outputs
    6. Merge passthroughs
    7. Update lineage
    8. Format result
    9. Generate stats

    Example:
        processor = BatchResultProcessor()

        result = processor.process(
            batch_results=batch_results,
            context_map=context_map,
            output_directory='/tmp/node_1_Agent',
            agent_config=agent_config
        )

        # result is the processed data in workflow format
    """

    def process(
        self,
        batch_results: List[BatchResult],
        context_map: Optional[Dict[str, Any]] = None,
        output_directory: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Process batch results through the pipeline.

        Args:
            batch_results: List of BatchResult objects from provider
            context_map: Map of custom_id -> original row data
            output_directory: Output directory path (for node extraction)
            agent_config: Agent configuration

        Returns:
            List of processed data in workflow format
        """
        # Stage 1: Initialize context
        ctx = self._stage_1_initialize_context(
            batch_results, context_map, output_directory, agent_config
        )

        # Stage 2: Reconcile requests with responses
        ctx = self._stage_2_reconcile(ctx)

        # Stage 3-4: Process batch results (success + errors)
        ctx = self._stage_3_4_process_results(ctx)

        # Stage 6: Merge passthroughs for missing/skipped records
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
        batch_results: List[BatchResult],
        context_map: Optional[Dict[str, Any]],
        output_directory: Optional[str],
        agent_config: Optional[Dict[str, Any]],
    ) -> BatchProcessingContext:
        """
        Stage 1: Initialize processing context.

        Extracts configuration values and prepares context for pipeline.
        """
        context_map = context_map or {}

        # Extract node index from output_directory
        node_idx = BatchPassthroughBuilder._extract_node_index(  # pylint: disable=protected-access
            output_directory
        )

        # Extract agent config values
        json_mode = True
        output_field = "content"
        if agent_config:
            json_mode = agent_config.get("json_mode", True)
            output_field = agent_config.get("output_field", "content")

        ctx = BatchProcessingContext(
            batch_results=batch_results,
            context_map=context_map,
            output_directory=output_directory,
            agent_config=agent_config,
            node_idx=node_idx,
            json_mode=json_mode,
            output_field=output_field,
        )

        logger.debug(
            "Initialized processing context: %d batch results, %d context records",
            len(batch_results),
            len(context_map),
        )

        return ctx

    def _stage_2_reconcile(self, ctx: BatchProcessingContext) -> BatchProcessingContext:
        """
        Stage 2: Reconcile requests with responses.

        Sets up BatchResultReconciler for tracking processed vs missing records.
        """
        ctx.reconciler = BatchResultReconciler(ctx.context_map)
        return ctx

    def _stage_3_4_process_results(self, ctx: BatchProcessingContext) -> BatchProcessingContext:
        """
        Stages 3-4: Process all batch results (success + errors).

        Iterates through batch results and processes each one, handling both
        successful results and errors.
        """
        for batch_result in ctx.batch_results:
            custom_id = batch_result.custom_id

            if batch_result.success and batch_result.content is not None:
                # Stage 3: Process successful result
                try:
                    items = self._process_successful_result(ctx, batch_result, custom_id)
                    ctx.processed_data.extend(items)
                    ctx.success_count += len(items)
                    ctx.reconciler.mark_processed(custom_id)

                    # Log individual item processing at DEBUG level
                    logger.debug(
                        "Processed batch result item",
                        extra={
                            "operation": "process_batch_item",
                            "custom_id": custom_id,
                            "items_generated": len(items),
                            "success": True,
                        },
                    )

                except Exception as e:  # pylint: disable=broad-exception-caught
                    # Catch all exceptions to prevent one item from breaking entire batch
                    # Processing exception - create error item
                    error_item = self._create_error_item(
                        ctx,
                        custom_id,
                        f"Processing error: {str(e)}",
                        batch_result.metadata,
                        batch_result.content,
                    )
                    ctx.processed_data.append(error_item)
                    ctx.error_count += 1
                    ctx.reconciler.mark_processed(custom_id)

                    # Log processing exception at DEBUG level
                    logger.debug(
                        "Batch result item processing failed",
                        extra={
                            "operation": "process_batch_item",
                            "custom_id": custom_id,
                            "success": False,
                            "error": str(e),
                        },
                    )

            else:
                # Stage 4: Process error result
                error_item = self._create_error_item(
                    ctx,
                    custom_id,
                    batch_result.error or "Batch processing failed",
                    batch_result.metadata,
                )
                ctx.processed_data.append(error_item)
                ctx.error_count += 1
                ctx.reconciler.mark_processed(custom_id)

                # Log error result at DEBUG level
                logger.debug(
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
    ) -> List[Dict[str, Any]]:
        """
        Stage 5: Build agent output from successful batch result.

        Handles all transformations for a successful result:
        - JSON mode handling
        - Context scope passthrough
        - Data transformation
        - Metadata addition
        - Lineage tracking
        - Loop correlation ID
        """
        # Step 1: Handle json_mode
        generated_obj = batch_result.content
        if not ctx.json_mode and isinstance(generated_obj, str):
            generated_obj = {ctx.output_field: generated_obj}

        # Step 2: Ensure list format
        generated_list = DataTransformer.ensure_list(generated_obj)

        # Step 3: Get original row data
        original_row = ctx.reconciler.get_record_by_id(custom_id)
        original_source_guid = ctx.reconciler.get_source_guid(custom_id)

        # Step 4: Apply context_scope.passthrough (if configured)
        if ctx.agent_config and custom_id in ctx.context_map:
            generated_list = self._apply_context_passthrough(
                ctx, custom_id, generated_list, original_row
            )

        # Step 5: Transform structure (convert to workflow format)
        structured_items = DataTransformer.transform_structure(
            [{original_source_guid: generated_list}]
        )

        # Step 6: Add metadata, lineage, IDs to each item
        for idx, item in enumerate(structured_items):
            # Metadata
            item["metadata"] = batch_result.metadata or {}

            # Lineage tracking (if node_idx available)
            if ctx.node_idx is not None:
                item_node_id = IDGenerator.generate_node_id(ctx.node_idx)
                item["node_id"] = item_node_id
                item["lineage"] = LineageBuilder.build_lineage(original_row, item_node_id)

            # Target ID (ensure present)
            if "target_id" not in item or not item["target_id"]:
                item["target_id"] = original_row.get("target_id", IDGenerator.generate_target_id())

            # Source GUID (ensure present)
            if "source_guid" not in item or not item["source_guid"]:
                item["source_guid"] = original_source_guid

            # Loop correlation ID (if agent_config present)
            if ctx.agent_config:
                record_index = ctx.reconciler.get_record_index(custom_id)
                if record_index >= 0:
                    structured_items[idx] = LoopIdGenerator.add_loop_correlation_id(
                        item, ctx.agent_config, record_index=record_index
                    )

        return structured_items

    def _apply_context_passthrough(
        self,
        ctx: BatchProcessingContext,
        custom_id: str,
        generated_list: List[Any],
        original_row: Dict[str, Any],
    ) -> List[Any]:
        """
        Apply context_scope.passthrough fields to generated items.

        Handles both pre-computed passthrough fields and fallback behavior.
        """
        # Check for pre-computed passthrough fields
        stored_passthrough = ctx.context_map[custom_id].get("_passthrough_fields", {})

        if stored_passthrough:
            # Use pre-computed passthrough
            # pylint: disable=import-outside-toplevel
            from agent_actions.utilities.context_scope.context_scope_processor import (
                ContextScopeProcessor,
            )

            generated_list = ContextScopeProcessor.merge_passthrough_fields(
                generated_list, stored_passthrough
            )

        elif ctx.agent_config.get("context_scope", {}).get("passthrough"):
            # Fallback: old behavior for backward compatibility
            passthrough_refs = ctx.agent_config.get("context_scope", {}).get("passthrough", [])
            passthrough_fields = []

            for field_ref in passthrough_refs:
                try:
                    # pylint: disable=import-outside-toplevel
                    from agent_actions.utilities.context_scope.context_scope_processor import (
                        ContextScopeProcessor,
                    )

                    _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                    passthrough_fields.append(field_name)
                except ValueError:
                    # If parsing fails, use the whole string as field name
                    passthrough_fields.append(field_ref)

            # Get original content
            original_content = original_row.get("content", original_row)

            # Merge passthrough fields
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

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _create_error_item(
        self,
        ctx: BatchProcessingContext,
        custom_id: str,
        error_message: str,
        metadata: Optional[Dict[str, Any]] = None,
        raw_content: Any = None,
    ) -> Dict[str, Any]:
        """
        Create an error item for failed batch results.

        Args:
            ctx: Processing context
            custom_id: The custom ID that failed
            error_message: Error message
            metadata: Optional metadata from batch result
            raw_content: Optional raw content (for processing errors)

        Returns:
            Error item dict
        """
        source_guid = ctx.reconciler.get_source_guid(custom_id, fallback=custom_id or "unknown")

        error_item = {
            "source_guid": source_guid,
            "error": error_message,
            "metadata": metadata or {},
        }

        # Include raw_content for processing errors (helps debugging)
        if raw_content is not None:
            error_item["raw_content"] = raw_content

        return error_item

    def _stage_6_merge_passthroughs(self, ctx: BatchProcessingContext) -> BatchProcessingContext:
        """
        Stage 6: Merge passthrough records for missing/skipped items.

        Uses BatchResultReconciler to find records that need passthrough treatment,
        then uses BatchPassthroughBuilder to create properly formatted passthrough items.
        """
        # Get reconciliation result
        reconciliation = ctx.reconciler.reconcile()

        # Build passthrough items for missing/skipped records
        if reconciliation.passthrough_records:
            builder = BatchPassthroughBuilder(ctx.output_directory)

            for custom_id, original_row in reconciliation.passthrough_records:
                # Legacy behavior: Always use 'conditional_clause_failed' reason
                # This ensures 'skipped_by_conditional' metadata flag (matches legacy)
                reason = "conditional_clause_failed"

                # Build passthrough item
                passthrough_item = builder._build_item(  # pylint: disable=protected-access
                    original_row, reason, custom_id
                )
                # Remove internal tracking field
                passthrough_item.pop("_batch_filter_status", None)

                ctx.processed_data.append(passthrough_item)
                ctx.passthrough_count += 1

        return ctx
