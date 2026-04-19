"""Context preparation service for agent builder."""

import json
import logging

from agent_actions.utils.json_safety import ensure_json_safe

logger = logging.getLogger(__name__)


class ContextService:
    """Handles context preparation and transformation for agents."""

    @staticmethod
    def prepare_context_data(
        context_data_str: str | dict,
        original_context: str | dict | None,
        is_tool: bool,
    ) -> str | dict:
        """
        Prepare context data for LLM/tool invocation.

        CRITICAL: Tools and LLMs now share the same llm_context to ensure
        consistent behavior across vendors.

        Args:
            context_data_str: Context data for LLM (may have context_scope.drop applied)
            original_context: Original untransformed context for tools (optional)
            is_tool: Whether this is a tool vendor invocation

        Returns:
            Prepared context data (str or dict depending on vendor needs)
        """
        # For tool vendors, return llm_context as-is (dict or str)
        if is_tool:
            return context_data_str

        # For LLM vendors, convert to JSON string if dict
        if isinstance(context_data_str, str):
            return context_data_str
        return json.dumps(ensure_json_safe(context_data_str), ensure_ascii=False)

    @staticmethod
    def prepare_tool_context(
        context_data_str: str | dict, original_context: str | dict | None
    ) -> str:
        """
        Prepare tool context as JSON string for tool injection.

        CRITICAL: Tools and LLMs now share the same llm_context.

        Args:
            context_data_str: Transformed context data (with context_scope.drop applied)
            original_context: Original untransformed context for tools (optional)

        Returns:
            JSON string of tool context
        """
        result = ContextService.prepare_context_data(
            context_data_str, original_context, is_tool=False
        )
        # Ensure string return type for backward compatibility
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)
