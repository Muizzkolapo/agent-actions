"""Enrichment pipeline for processing results."""

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, cast

from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    EnricherExecutedEvent,
    EnrichmentPipelineCompleteEvent,
    EnrichmentPipelineStartedEvent,
)

from .types import ProcessingContext, ProcessingResult, ProcessingStatus

logger = logging.getLogger(__name__)


class Enricher(ABC):
    """Base class for result enrichers."""

    @abstractmethod
    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Enrich a processing result, returning the modified result."""
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

        use_per_item_parent_lookup = result.source_guid is None and not context.is_first_stage

        parent_item = None
        if not use_per_item_parent_lookup:
            parent_item = self._get_parent_item(result.source_guid, context)

        source_data_len = len(context.source_data) if context.source_data else 0

        for i, item in enumerate(result.data):
            node_id = f"{base_node_id}_{i}" if len(result.data) > 1 else base_node_id

            if (
                result.source_mapping is not None
                and context.source_data is not None
                and i in result.source_mapping
            ):
                # Index-based lookup — resolve parent by source_mapping
                source_idx = result.source_mapping[i]
                if isinstance(source_idx, list):
                    # Many-to-one: multiple input records merged into one output
                    source_items = [
                        context.source_data[idx] for idx in source_idx if idx < source_data_len
                    ]
                    skipped = len(source_idx) - len(source_items)
                    if skipped:
                        logger.warning(
                            "source_mapping[%d]: %d of %d indices out of bounds (source_data has %d items)",
                            i,
                            skipped,
                            len(source_idx),
                            source_data_len,
                        )
                    result.data[i] = LineageBuilder.add_lineage_tracking_from_sources(
                        obj=item,
                        source_items=source_items,
                        node_id=node_id,
                    )
                    continue
                elif source_idx is None:
                    # Synthetic record — no parent, gets fresh lineage
                    parent_item = None
                else:
                    # One-to-one: single input record
                    if source_idx < source_data_len:
                        parent_item = context.source_data[source_idx]
                    else:
                        logger.warning(
                            "source_mapping[%d] -> %d is out of bounds (source_data has %d items)",
                            i,
                            source_idx,
                            source_data_len,
                        )
                        parent_item = None
            elif use_per_item_parent_lookup:
                item_source_guid = item.get("source_guid")
                parent_item = self._get_parent_item(item_source_guid, context)

            result.data[i] = LineageBuilder.add_unified_lineage(
                obj=item,
                node_id=node_id,
                parent_item=parent_item,
            )

        result.node_id = base_node_id
        return result

    def _get_parent_item(self, source_guid: str | None, context: ProcessingContext) -> dict | None:
        """Look up parent item for lineage chaining; returns None for first-stage."""
        if context.is_first_stage or not source_guid:
            return None

        if context.current_item:
            return context.current_item

        if not context.source_data:
            return None

        for source_item in context.source_data:
            if source_item.get("source_guid") == source_guid:
                return source_item

        return None


class MetadataEnricher(Enricher):
    """Add LLM response metadata."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Add metadata from LLM response or pre-extracted metadata dict."""
        if not result.executed:
            return result

        from agent_actions.utils.field_management import FieldManager

        if result.pre_extracted_metadata is not None:
            metadata_dict = result.pre_extracted_metadata
        else:
            from agent_actions.utils.metadata import MetadataExtractor

            metadata = MetadataExtractor.extract_from_response(
                response=result.raw_response,
                agent_config=cast(dict[str, Any], context.agent_config),
            )
            metadata_dict = metadata.to_dict()

        for item in result.data:
            FieldManager.add_metadata(item, metadata=metadata_dict)

        return result


class VersionIdEnricher(Enricher):
    """Add version correlation IDs."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Add version correlation ID to each item.

        For 1→N expansions (result.is_expansion=True), always assigns fresh
        IDs — each expanded item is a new logical entity.

        For 1:1 passthroughs, respects existing version_correlation_id
        carried forward by RecordEnvelope. Only assigns if absent
        (e.g. first-stage records that don't yet have one).
        """
        if result.status == ProcessingStatus.FILTERED:
            return result

        # Skip when record_index is invalid (e.g. -1 from batch reconciler miss)
        if context.record_index < 0:
            return result

        from agent_actions.utils.correlation import VersionIdGenerator

        for i, item in enumerate(result.data):
            if not result.is_expansion and item.get("version_correlation_id"):
                continue
            result.data[i] = VersionIdGenerator.add_version_correlation_id(
                item,
                cast(dict[str, Any], context.agent_config),
                record_index=context.record_index + i,
                force=result.is_expansion,
            )

        return result


class PassthroughEnricher(Enricher):
    """Merge passthrough fields into results."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Merge passthrough_fields into the current action's content namespace.

        Content is namespaced: ``{"action_a": {...}, "action_b": {...}}``.
        Passthrough fields are merged into ``content[context.action_name]``,
        not at the top level.
        """
        if not result.passthrough_fields:
            return result

        action_name = context.action_name
        for item in result.data:
            content = item.get("content")
            if not isinstance(content, dict):
                continue
            ns = content.get(action_name)
            if isinstance(ns, dict):
                ns.update(result.passthrough_fields)
            else:
                content[action_name] = dict(result.passthrough_fields)

        return result


class RequiredFieldsEnricher(Enricher):
    """Ensure required fields are present."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Ensure required fields in each item."""
        if result.status == ProcessingStatus.FILTERED:
            return result

        from agent_actions.utils.field_management import FieldManager

        fm = FieldManager()
        for i, item in enumerate(result.data):
            # Prefer item-level source_guid (set by metadata reattachment in FILE mode)
            # over result-level source_guid (which is None for FILE mode).
            item_source_guid = item.get("source_guid") or result.source_guid or ""
            result.data[i] = fm.ensure_required_fields(item, item_source_guid, context.action_name)

        return result


class RecoveryEnricher(Enricher):
    """Add recovery metadata (_recovery) to output records."""

    def enrich(self, result: ProcessingResult, context: ProcessingContext) -> ProcessingResult:
        """Add _recovery field to each output item when recovery occurred."""
        if result.status == ProcessingStatus.FILTERED:
            return result

        if result.recovery_metadata is None or result.recovery_metadata.is_empty():
            return result

        recovery_dict = result.recovery_metadata.to_dict()
        if recovery_dict:
            for item in result.data:
                item["_recovery"] = recovery_dict

        return result


class EnrichmentPipeline:
    """Pipeline of enrichers applied in sequence."""

    def __init__(self, enrichers: list[Enricher] | None = None):
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
        """Run result through all enrichers in sequence."""
        start_time = datetime.now(UTC)

        fire_event(
            EnrichmentPipelineStartedEvent(
                enricher_count=len(self.enrichers),
            )
        )

        try:
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
                    logger.exception("Enricher %s failed", enricher_name)
                    fire_event(
                        EnricherExecutedEvent(
                            enricher_name=enricher_name,
                            status="failed",
                        )
                    )
                    raise
        finally:
            elapsed_time = (datetime.now(UTC) - start_time).total_seconds()
            fire_event(
                EnrichmentPipelineCompleteEvent(
                    enricher_count=len(self.enrichers),
                    elapsed_time=elapsed_time,
                )
            )

        return result
