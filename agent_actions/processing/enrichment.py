"""Enrichment pipeline for processing results."""

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, cast

from agent_actions.errors.validation import DataValidationError
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

        source_index = self._index_by_source_guid(context.source_data)
        parent_index = self._index_by_source_guid(context.parent_records)

        parent_item = None
        if not use_per_item_parent_lookup:
            parent_item = self._get_parent_item(
                result.source_guid, context, source_index, parent_index
            )

        source_data_len = len(context.source_data) if context.source_data else 0

        for i, item in enumerate(result.data):
            node_id = f"{base_node_id}_{i}" if len(result.data) > 1 else base_node_id

            # 1→N expansions: each child needs a unique target_id so that
            # batch custom_ids are unique and context_map keys don't collide.
            # The parent's target_id moves to parent_target_id for lineage.
            if result.is_expansion:
                old_target_id = item.get("target_id")
                item["target_id"] = IDGenerator.generate_target_id()
                if old_target_id:
                    item["parent_target_id"] = old_target_id
                # Each expansion child gets its own source_guid to prevent
                # UNIQUE constraint collisions when written to source_data.
                old_source_guid = item.get("source_guid")
                item["source_guid"] = IDGenerator.generate_source_guid()
                if old_source_guid:
                    item["parent_source_guid"] = old_source_guid
                # New GUIDs have no upstream deltas — store as full
                item["_delta_mode"] = "full"

            if (
                result.source_mapping is not None
                and context.source_data is not None
                and i in result.source_mapping
            ):
                source_idx = result.source_mapping[i]
                if isinstance(source_idx, list):
                    # Many-to-one: multiple input records merged into one output
                    source_items = [
                        context.source_data[idx] for idx in source_idx if idx < source_data_len
                    ]
                    source_items = [
                        self._with_parent_fallback(s, parent_index) for s in source_items
                    ]
                    skipped = len(source_idx) - len(source_items)
                    if skipped:
                        logger.warning(
                            "source_mapping[%d]: %d of %d indices out of bounds "
                            "(source_data has %d items, action=%s)",
                            i,
                            skipped,
                            len(source_idx),
                            source_data_len,
                            context.action_name,
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
                        parent_item = self._with_parent_fallback(
                            context.source_data[source_idx], parent_index
                        )
                    else:
                        logger.warning(
                            "source_mapping[%d] -> %d is out of bounds "
                            "(source_data has %d items, action=%s)",
                            i,
                            source_idx,
                            source_data_len,
                            context.action_name,
                        )
                        parent_item = None
            elif use_per_item_parent_lookup:
                item_source_guid = item.get("source_guid")
                parent_item = self._get_parent_item(
                    item_source_guid, context, source_index, parent_index
                )

            result.data[i] = LineageBuilder.add_unified_lineage(
                obj=item,
                node_id=node_id,
                parent_item=parent_item,
            )

        result.node_id = base_node_id
        return result

    @staticmethod
    def _index_by_source_guid(
        records: list[dict[str, Any]] | None,
    ) -> dict[str, dict] | None:
        """Build a {source_guid: record} dict, or None when *records* is empty."""
        if not records:
            return None
        return {sg: r for r in records if (sg := r.get("source_guid")) is not None}

    @staticmethod
    def _with_parent_fallback(item: dict, parent_index: dict[str, dict] | None) -> dict:
        """If *item* lacks lineage, look up a richer match in parent_index by source_guid."""
        from agent_actions.utils.lineage import LineageBuilder

        if LineageBuilder.is_lineage_bearing(item):
            return item
        if parent_index is None:
            return item
        sg = item.get("source_guid")
        if sg is None:
            return item
        richer = parent_index.get(sg)
        return richer if richer is not None else item

    def _get_parent_item(
        self,
        source_guid: str | None,
        context: ProcessingContext,
        source_index: dict[str, dict] | None = None,
        parent_index: dict[str, dict] | None = None,
    ) -> dict | None:
        """Look up parent item for lineage chaining; returns None for first-stage.

        Precedence (highest first):
        1. ``context.current_item`` — explicit parent set by the strategy.
        2. ``context.parent_records`` (or ``parent_index`` for O(1) lookup) —
           previous-stage output that carries lineage.
        3. ``context.source_data`` (or ``source_index`` for O(1) lookup) —
           fallback when source_data is itself lineage-bearing.
        """
        if context.is_first_stage or not source_guid:
            return None

        if context.current_item:
            current_guid = context.current_item.get("source_guid")
            if current_guid is None or current_guid == source_guid:
                return context.current_item

        if parent_index is None:
            parent_index = self._index_by_source_guid(context.parent_records)
        if parent_index is not None:
            hit = parent_index.get(source_guid)
            if hit is not None:
                return hit

        if not context.source_data:
            return None

        if source_index is None:
            source_index = self._index_by_source_guid(context.source_data)
        return source_index.get(source_guid) if source_index else None


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
        """Merge namespaced passthrough_fields into content as sibling namespaces.

        passthrough_fields is ``{namespace: {field: value}}``. Each namespace
        lands at content level next to the action's own namespace so a
        downstream ``ns.field`` observe resolves against ``content[ns]``.
        Idempotent with the transform-time merge: existing namespaces win
        field-by-field and the action's own output is never touched.
        """
        if not result.passthrough_fields:
            return result

        from agent_actions.utils.transformation.passthrough import (
            merge_passthrough_namespaces,
        )

        action_name = context.action_name
        for item in result.data:
            content = item.get("content")
            if not isinstance(content, dict):
                continue
            merge_passthrough_namespaces(content, result.passthrough_fields, action_name)

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
            # A record is stamped at its source or producer; a blank one here is an
            # upstream invariant violation — fail loud, don't backfill an empty string.
            item_source_guid = item.get("source_guid") or result.source_guid
            if not item_source_guid:
                raise DataValidationError(
                    f"Record {i} reached '{context.action_name}' enrichment without a "
                    f"source_guid; it must be stamped at its source or producer",
                    context={"action": context.action_name, "record_index": i},
                )
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

        # LLM can return malformed data (strings, lists, None) that would
        # crash every enricher's .get() calls with AttributeError.
        if any(not isinstance(item, dict) for item in result.data):
            valid_items = [item for item in result.data if isinstance(item, dict)]
            invalid_count = len(result.data) - len(valid_items)
            logger.warning(
                "Filtered %d non-dict items from result.data (action=%s)",
                invalid_count,
                context.action_name,
            )
            result.data = valid_items
            if not valid_items:
                result.status = ProcessingStatus.FAILED
                result.error = (
                    f"All {invalid_count} items in result.data were non-dict "
                    f"(action={context.action_name}) — enrichment skipped"
                )
                return result

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
                    logger.exception(
                        "Enricher %s failed for action=%s source_guid=%s",
                        enricher_name,
                        context.action_name,
                        result.source_guid,
                    )
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
