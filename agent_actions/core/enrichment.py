"""Enrichment pipeline for processing results."""

from abc import ABC, abstractmethod
from typing import List

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

        from agent_actions.utilities.id_generation import IDGenerator
        from agent_actions.utilities.lineage import LineageBuilder

        base_node_id = IDGenerator.generate_node_id(context.action_name)

        for i, item in enumerate(result.data):
            node_id = f"{base_node_id}_{i}" if len(result.data) > 1 else base_node_id

            # Use unified lineage method (to be created in Phase 5)
            # For now, manually add lineage fields
            item["node_id"] = node_id
            item["lineage"] = LineageBuilder.build_lineage({}, node_id)

        result.node_id = base_node_id
        return result


class MetadataEnricher(Enricher):
    """Add LLM response metadata."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Add metadata from LLM response."""
        if not result.executed:
            return result

        from agent_actions.utilities.field_management import FieldManager
        from agent_actions.utilities.metadata import MetadataExtractor

        metadata = MetadataExtractor.extract_from_response(
            response=result.raw_response,
            agent_config=context.agent_config,
        )

        for item in result.data:
            FieldManager.add_metadata(item, metadata=metadata.to_dict())

        return result


class LoopIdEnricher(Enricher):
    """Add loop correlation IDs."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Add loop correlation ID to each item."""
        if result.status == ProcessingStatus.FILTERED:
            return result

        from agent_actions.utilities.correlation import LoopIdGenerator

        for i, item in enumerate(result.data):
            result.data[i] = LoopIdGenerator.add_loop_correlation_id(
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

        from agent_actions.utilities.field_management import FieldManager

        for item in result.data:
            FieldManager().ensure_required_fields(item, result.source_guid, 0)

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
                LoopIdEnricher(),
                PassthroughEnricher(),
                RequiredFieldsEnricher(),
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
        for enricher in self.enrichers:
            result = enricher.enrich(result, context)
        return result
