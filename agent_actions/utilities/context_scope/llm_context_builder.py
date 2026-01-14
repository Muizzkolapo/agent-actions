"""
LLM Context Builder - Mode-specific implementations for batch and realtime.
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
        context_scope: Optional[Dict[str, Any]] = None,
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

        # Add observed fields from llm_context (context_scope.observe)
        if llm_context:
            llm_full_context.update(llm_context)

        # Remove dropped fields (context_scope.drop) AFTER observe/static merge
        if context_scope and context_scope.get("drop"):
            for field_ref in context_scope.get("drop", []):
                try:
                    # Parse field reference (e.g., 'source.api_key')
                    action_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                    if action_name == "seed":
                        seed_data = llm_full_context.get("seed")
                        if isinstance(seed_data, dict):
                            seed_data.pop(field_name, None)
                            if not seed_data:
                                llm_full_context.pop("seed", None)
                    else:
                        llm_full_context.pop(field_name, None)
                except ValueError:
                    # Invalid field reference, skip silently (backward compatible)
                    continue

        return llm_full_context

    @staticmethod
    def build_llm_context_for_realtime(
        processed_context: Dict[str, Any],
        llm_additional_context: Optional[Dict[str, Any]],
        context_scope: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build LLM context for realtime mode.

        Uses DataTransformer for drops and dict merge for observe.
        """
        # Return unchanged if not a dict
        if not isinstance(processed_context, dict):
            return processed_context

        result_context = processed_context

        # Merge context_scope.observe/static fields into context JSON (dict spread)
        if llm_additional_context and isinstance(result_context, dict):
            result_context = {**result_context, **llm_additional_context}

        # Apply context_scope.drop field filtering using DataTransformer AFTER merge
        if context_scope and context_scope.get("drop"):
            seed_drop_fields = []
            drop_fields = []
            for field_ref in context_scope.get("drop", []):
                try:
                    # Parse field reference (e.g., 'source.api_key')
                    action_name, field_name = ContextScopeProcessor.parse_field_reference(field_ref)
                    if action_name == "seed":
                        seed_drop_fields.append(field_name)
                    else:
                        drop_fields.append(field_name)
                except ValueError:
                    # Invalid field reference, skip silently (backward compatible)
                    continue

            if seed_drop_fields and isinstance(result_context.get("seed"), dict):
                for field_name in seed_drop_fields:
                    result_context["seed"].pop(field_name, None)
                if not result_context["seed"]:
                    result_context.pop("seed", None)

            if drop_fields:
                result_context = DataTransformer.remove_schema_objects(result_context, drop_fields)

        return result_context
