"""Adapter to bridge batch processing state into the enrichment pipeline."""

from typing import Any, Optional

from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingMode,
    ProcessingResult,
    RecoveryMetadata,
)


class BatchContextAdapter:
    """Converts batch state to ProcessingContext + ProcessingResult for EnrichmentPipeline."""

    @staticmethod
    def to_processing_context(
        agent_config: dict[str, Any],
        original_row: dict[str, Any],
        record_index: int,
        output_directory: Optional[str] = None,
    ) -> ProcessingContext:
        """
        Build a ProcessingContext from batch-side state.

        Args:
            agent_config: Agent configuration dict
            original_row: The original input row (used as parent for lineage)
            record_index: Position of this record in the batch (for version correlation)
            output_directory: Optional output directory path

        Returns:
            ProcessingContext configured for batch enrichment
        """
        return ProcessingContext(
            agent_config=agent_config,
            agent_name=agent_config.get("agent_type", "unknown_action"),
            mode=ProcessingMode.BATCH,
            is_first_stage=False,
            current_item=original_row,
            record_index=record_index,
            output_directory=output_directory,
        )

    @staticmethod
    def to_processing_result(
        data: list[dict[str, Any]],
        source_guid: str,
        pre_extracted_metadata: Optional[dict[str, Any]] = None,
        recovery_metadata: Optional[RecoveryMetadata] = None,
        passthrough_fields: Optional[dict[str, Any]] = None,
    ) -> ProcessingResult:
        """
        Build a ProcessingResult from batch-side data.

        Args:
            data: Transformed output items
            source_guid: Source GUID for this record
            pre_extracted_metadata: Already-extracted metadata dict from batch provider
            recovery_metadata: Recovery metadata if retry occurred
            passthrough_fields: Passthrough fields to merge

        Returns:
            ProcessingResult ready for enrichment pipeline
        """
        return ProcessingResult.success(
            data=data,
            source_guid=source_guid,
            pre_extracted_metadata=pre_extracted_metadata,
            recovery_metadata=recovery_metadata,
            passthrough_fields=passthrough_fields or {},
        )
