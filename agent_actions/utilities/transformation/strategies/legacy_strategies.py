"""
Legacy Passthrough Strategies.

These strategies handle transformation using the old
context_scope.passthrough extraction method (backward compatibility).
"""
from typing import Dict, List, Optional
from .base import IPassthroughTransformStrategy
from agent_actions.preprocessing.data_transformer import DataTransformer


class LegacyStructuredStrategy(IPassthroughTransformStrategy):
    """
    Handle legacy context_scope passthrough with structured data.

    Extracts fields from context_scope.passthrough config,
    then merges into structured data.
    """

    def can_handle(
        self,
        data: List,
        passthrough_fields: Optional[Dict],
        agent_config: Dict,
        already_structured: bool
    ) -> bool:
        """Check if we have no precomputed fields, structured data."""
        has_passthrough_config = self._has_passthrough_config(agent_config)
        return (
            (passthrough_fields is None or len(passthrough_fields) == 0)
            and already_structured
            and has_passthrough_config
        )

    def transform(
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None
    ) -> List:
        """Extract and merge legacy passthrough fields."""
        fields_to_merge = self._extract_legacy_fields(agent_config)

        context_for_passthrough = context_data
        if (
            isinstance(context_data, dict)
            and 'content' in context_data
            and isinstance(context_data['content'], dict)
        ):
            context_for_passthrough = context_data['content']

        contents = [item['content'] for item in data]
        updated = []
        for content in contents:
            if isinstance(content, dict):
                updated.append(
                    DataTransformer.update_schema_objects(
                        context_for_passthrough,
                        content,
                        fields_to_merge
                    )
                )
            else:
                content_dict = {'content': content}
                updated.append(
                    DataTransformer.update_schema_objects(
                        context_for_passthrough,
                        content_dict,
                        fields_to_merge
                    )
                )
        return DataTransformer.transform_structure([{source_guid: updated}])

    @staticmethod
    def _has_passthrough_config(agent_config: Dict) -> bool:
        """Check if agent_config has passthrough configuration."""
        context_scope = agent_config.get('context_scope', {})
        return bool(context_scope and context_scope.get('passthrough'))

    @staticmethod
    def _extract_legacy_fields(agent_config: Dict) -> List[str]:
        """Extract field names from context_scope.passthrough."""
        context_scope = agent_config.get('context_scope', {})
        fields_to_merge = []

        if context_scope and context_scope.get('passthrough'):
            passthrough_refs = context_scope.get('passthrough', [])
            for field_ref in passthrough_refs:
                # Parse 'action.field' -> 'field'
                if isinstance(field_ref, str) and '.' in field_ref:
                    parts = field_ref.split('.', 1)
                    if len(parts) == 2:
                        field_name = parts[1]
                        if field_name not in fields_to_merge:
                            fields_to_merge.append(field_name)

        return fields_to_merge


class LegacyUnstructuredStrategy(IPassthroughTransformStrategy):
    """
    Handle legacy context_scope passthrough with unstructured data.

    Extracts fields from context_scope.passthrough config,
    then merges into unstructured data.
    """

    def can_handle(
        self,
        data: List,
        passthrough_fields: Optional[Dict],
        agent_config: Dict,
        already_structured: bool
    ) -> bool:
        """Check if we have no precomputed fields, unstructured data."""
        has_passthrough_config = (
            LegacyStructuredStrategy._has_passthrough_config(agent_config)
        )
        return (
            (passthrough_fields is None or len(passthrough_fields) == 0)
            and not already_structured
            and has_passthrough_config
        )

    def transform(
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None
    ) -> List:
        """Extract and merge legacy passthrough fields."""
        fields_to_merge = (
            LegacyStructuredStrategy._extract_legacy_fields(agent_config)
        )

        context_for_passthrough = context_data
        if (
            isinstance(context_data, dict)
            and 'content' in context_data
            and isinstance(context_data['content'], dict)
        ):
            context_for_passthrough = context_data['content']

        updated = []
        for item in data:
            if isinstance(item, dict):
                updated.append(
                    DataTransformer.update_schema_objects(
                        context_for_passthrough,
                        item,
                        fields_to_merge
                    )
                )
            else:
                item_dict = {'content': item}
                updated.append(
                    DataTransformer.update_schema_objects(
                        context_for_passthrough,
                        item_dict,
                        fields_to_merge
                    )
                )
        return DataTransformer.transform_structure([{source_guid: updated}])


class NoOpStrategy(IPassthroughTransformStrategy):
    """
    No-op strategy for structured data with no passthrough fields.

    Returns data as-is without any transformation.
    """

    def can_handle(
        self,
        data: List,
        passthrough_fields: Optional[Dict],
        agent_config: Dict,
        already_structured: bool
    ) -> bool:
        """Check if structured data with no passthrough."""
        has_passthrough_config = (
            LegacyStructuredStrategy._has_passthrough_config(agent_config)
        )
        return (
            already_structured
            and not has_passthrough_config
            and (passthrough_fields is None or len(passthrough_fields) == 0)
        )

    def transform(
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None
    ) -> List:
        """Return data unchanged."""
        return data


class DefaultStructureStrategy(IPassthroughTransformStrategy):
    """
    Default strategy for unstructured data with no passthrough fields.

    Structures the data using DataTransformer without any merging.
    """

    def can_handle(
        self,
        data: List,
        passthrough_fields: Optional[Dict],
        agent_config: Dict,
        already_structured: bool
    ) -> bool:
        """
        Fallback strategy - handles all remaining cases.

        Returns True if no other strategy matches.
        """
        return True  # Catch-all

    def transform(
        self,
        data: List,
        context_data: Dict,
        source_guid: str,
        agent_config: Dict,
        passthrough_fields: Optional[Dict] = None
    ) -> List:
        """Structure data without passthrough."""
        return DataTransformer.transform_structure([{source_guid: data}])
