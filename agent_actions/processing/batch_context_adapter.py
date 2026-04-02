"""Adapter to bridge batch processing state into the enrichment pipeline."""

from typing import Any, cast

from agent_actions.config.types import ActionConfigDict, RunMode
from agent_actions.processing.types import (
    ProcessingContext,
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
        output_directory: str | None = None,
    ) -> ProcessingContext:
        """Build a ProcessingContext from batch-side state."""
        return ProcessingContext(
            agent_config=cast(ActionConfigDict, agent_config),
            agent_name=agent_config.get("agent_type", "unknown_action"),
            mode=RunMode.BATCH,
            is_first_stage=False,
            current_item=original_row,
            record_index=record_index,
            output_directory=output_directory,
        )

    @staticmethod
    def to_processing_result(
        data: list[dict[str, Any]],
        source_guid: str,
        pre_extracted_metadata: dict[str, Any] | None = None,
        recovery_metadata: RecoveryMetadata | None = None,
        passthrough_fields: dict[str, Any] | None = None,
    ) -> ProcessingResult:
        """Build a ProcessingResult from batch-side data."""
        return ProcessingResult.success(
            data=data,
            source_guid=source_guid,
            pre_extracted_metadata=pre_extracted_metadata,
            recovery_metadata=recovery_metadata,
            passthrough_fields=passthrough_fields or {},
        )
