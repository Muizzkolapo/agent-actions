"""
Unified LLM context building for batch and realtime modes.

Handles context_scope.drop (field removal) and context_scope.observe (field merging)
with mode-specific implementations to maintain backward compatibility.
"""

from typing import Dict, Any, Optional
from agent_actions.utilities.context_scope.context_scope_processor import ContextScopeProcessor
from agent_actions.preprocessing.transformation.data_transformer import DataTransformer


class LLMContextBuilder:
    """Unified builder for LLM context across batch and realtime modes."""

    @staticmethod
    def build_llm_context_for_batch(
        row_content: Dict[str, Any],
        llm_context: Dict[str, Any],
        context_scope: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build LLM context for batch mode.

        Uses dict.pop() for drops and dict.update() for observe.
        """
        # Start with copy of row content (avoid mutating original)
        if not isinstance(row_content, dict):
            llm_full_context = {}
        else:
            llm_full_context = row_content.copy()

        # Remove dropped fields (context_scope.drop)
        if context_scope and context_scope.get('drop'):
            for field_ref in context_scope.get('drop', []):
                try:
                    # Parse field reference (e.g., 'source.api_key' -> 'api_key')
                    _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                    llm_full_context.pop(field_name, None)
                except ValueError:
                    # Invalid field reference, skip silently (backward compatible)
                    continue

        # Add observed fields from llm_context (context_scope.observe)
        if llm_context:
            llm_full_context.update(llm_context)

        return llm_full_context

    @staticmethod
    def build_llm_context_for_realtime(
        processed_context: Dict[str, Any],
        llm_additional_context: Optional[Dict[str, Any]],
        context_scope: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build LLM context for realtime mode.

        Uses DataTransformer for drops and dict merge for observe.
        """
        # Return unchanged if not a dict
        if not isinstance(processed_context, dict):
            return processed_context

        result_context = processed_context

        # Apply context_scope.drop field filtering using DataTransformer
        if context_scope and context_scope.get('drop'):
            # Extract field names from context_scope.drop
            drop_fields = []
            for field_ref in context_scope.get('drop', []):
                try:
                    # Parse field reference (e.g., 'source.api_key' -> 'api_key')
                    _, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                    drop_fields.append(field_name)
                except ValueError:
                    # Invalid field reference, skip silently (backward compatible)
                    continue

            # Remove dropped fields from context using DataTransformer
            if drop_fields:
                result_context = DataTransformer.remove_schema_objects(result_context, drop_fields)

        # Merge context_scope.observe fields into context JSON (dict spread)
        if llm_additional_context and isinstance(result_context, dict):
            result_context = {**result_context, **llm_additional_context}

        return result_context
