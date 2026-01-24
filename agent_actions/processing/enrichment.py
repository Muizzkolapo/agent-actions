"""Enrichment pipeline for processing results."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    EnrichmentPipelineCompleteEvent,
    EnrichmentPipelineStartedEvent,
    EnricherExecutedEvent,
)

from .types import ProcessingContext, ProcessingResult, ProcessingStatus


class Enricher(ABC):
    """Base class for result enrichers."""

    @abstractmethod
    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """
        Enrich a processing result.

        Args:
            result: ProcessingResult to enrich
            context: ProcessingContext with config and state

        Returns:
            Enriched ProcessingResult
        """
        pass


class LineageEnricher(Enricher):
    """Add lineage tracking to results."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Add lineage tracking using unified method."""
        if result.status == ProcessingStatus.FILTERED:
            return result

        from agent_actions.utils.id_generation import IDGenerator
        from agent_actions.utils.lineage import LineageBuilder

        base_node_id = IDGenerator.generate_node_id(context.action_name)

        # For FILE mode (result.source_guid is None), look up parent per-item
        # For RECORD mode, look up once using result.source_guid
        use_per_item_parent_lookup = result.source_guid is None and not context.is_first_stage

        # Pre-compute parent for RECORD mode (single parent for all items)
        parent_item = None
        if not use_per_item_parent_lookup:
            parent_item = self._get_parent_item(result.source_guid, context)

        for i, item in enumerate(result.data):
            node_id = f"{base_node_id}_{i}" if len(result.data) > 1 else base_node_id

            # For FILE mode, look up parent using each item's individual source_guid
            if use_per_item_parent_lookup:
                item_source_guid = item.get("source_guid")
                parent_item = self._get_parent_item(item_source_guid, context)

            # Use unified lineage method with parent lookup
            enriched = LineageBuilder.add_unified_lineage(
                obj=item, node_id=node_id, parent_item=parent_item
            )
            result.data[i] = enriched

        result.node_id = base_node_id
        return result

    def _get_parent_item(
        self, source_guid: Optional[str], context: ProcessingContext
    ) -> Optional[Dict]:
        """
        Get parent item for lineage chaining.

        In subsequent-stage processing, looks up the parent item from source_data
        using the source_guid to enable proper lineage chain propagation.

        Args:
            source_guid: Source GUID to lookup
            context: ProcessingContext with source_data

        Returns:
            Parent item dict if found, None otherwise
            None for first-stage processing (no parent)
        """
        # First-stage has no parent
        if context.is_first_stage or not source_guid:
            return None

        # Prefer per-record current item when available (preserves lineage chain)
        if context.current_item:
            return context.current_item

        # Look up parent in source_data
        if not context.source_data:
            return None

        for source_item in context.source_data:
            if source_item.get("source_guid") == source_guid:
                return source_item

        # Parent not found - graceful fallback
        return None


class MetadataEnricher(Enricher):
    """Add LLM response metadata."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Add metadata from LLM response."""
        if not result.executed:
            return result

        from agent_actions.utils.field_management import FieldManager
        from agent_actions.utils.metadata import MetadataExtractor

        metadata = MetadataExtractor.extract_from_response(
            response=result.raw_response,
            agent_config=context.agent_config,
        )

        for item in result.data:
            FieldManager.add_metadata(item, metadata=metadata.to_dict())

        return result


class VersionIdEnricher(Enricher):
    """Add version correlation IDs."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Add version correlation ID to each item."""
        if result.status == ProcessingStatus.FILTERED:
            return result

        from agent_actions.utils.correlation import VersionIdGenerator

        for i, item in enumerate(result.data):
            result.data[i] = VersionIdGenerator.add_version_correlation_id(
                item, context.agent_config, record_index=context.record_index
            )

        return result


class PassthroughEnricher(Enricher):
    """Merge passthrough fields into results."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Merge passthrough_fields into each item."""
        if not result.passthrough_fields:
            return result

        for item in result.data:
            content = item.get("content", item)
            if isinstance(content, dict):
                content.update(result.passthrough_fields)

        return result


class RequiredFieldsEnricher(Enricher):
    """Ensure required fields are present."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Ensure required fields in each item."""
        if result.status == ProcessingStatus.FILTERED:
            return result

        from agent_actions.utils.field_management import FieldManager

        for item in result.data:
            FieldManager().ensure_required_fields(item, result.source_guid, 0)

        return result


class RecoveryEnricher(Enricher):
    """Add recovery metadata (_recovery) to output records."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """
        Add _recovery field to each output item when recovery occurred.

        Per RFC_recovery.md, the _recovery field contains:
        - retry: {attempts, reason} when retry was triggered
        - reprompt: {attempts, passed, validation} when reprompt was triggered (future)
        """
        if result.status == ProcessingStatus.FILTERED:
            return result

        # Only add _recovery if recovery actually occurred
        if result.recovery_metadata is None or result.recovery_metadata.is_empty():
            return result

        recovery_dict = result.recovery_metadata.to_dict()
        if recovery_dict:
            for item in result.data:
                item["_recovery"] = recovery_dict

        return result


class EnrichmentPipeline:
    """Pipeline of enrichers applied in sequence."""

    def __init__(self, enrichers: List[Enricher] = None):
        """
        Initialize pipeline with enrichers.

        Args:
            enrichers: List of enrichers to apply. If None, uses default pipeline.
        """
        self.enrichers = (
            enrichers
            if enrichers is not None
            else [
                LineageEnricher(),
                MetadataEnricher(),
                VersionIdEnricher(),
                PassthroughEnricher(),
                RequiredFieldsEnricher(),
                RecoveryEnricher(),
            ]
        )

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """
        Run result through all enrichers in sequence.

        Args:
            result: ProcessingResult to enrich
            context: ProcessingContext with config

        Returns:
            Enriched ProcessingResult
        """
        # Capture start time before firing event
        from datetime import datetime

        start_time = datetime.now()

        # Fire pipeline started event
        fire_event(
            EnrichmentPipelineStartedEvent(
                enricher_count=len(self.enrichers),
            )
        )

        # Execute enrichers
        for enricher in self.enrichers:
            enricher_name = enricher.__class__.__name__
            try:
                result = enricher.enrich(result, context)
                fire_event(
                    EnricherExecutedEvent(
                        enricher_name=enricher_name,
                        status="success",
                    )
                )
            except Exception:
                fire_event(
                    EnricherExecutedEvent(
                        enricher_name=enricher_name,
                        status="failed",
                    )
                )
                raise

        # Fire pipeline complete event with timing
        elapsed_time = (datetime.now() - start_time).total_seconds()
        fire_event(
            EnrichmentPipelineCompleteEvent(
                enricher_count=len(self.enrichers),
                elapsed_time=elapsed_time,
            )
        )

        return result
