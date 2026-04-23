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
        is_tool: bool,
    ) -> str | dict:
        """
        Prepare context data for LLM/tool invocation.

        Tools receive namespaced data directly. LLMs receive JSON strings.

        Args:
            context_data_str: Context data (may have context_scope.drop applied)
            is_tool: Whether this is a tool vendor invocation

        Returns:
            Prepared context data (str or dict depending on vendor needs)
        """
        # Tools receive namespaced data directly — no flattening.
        if is_tool:
            return context_data_str

        # For LLM vendors, convert to JSON string if dict
        if isinstance(context_data_str, str):
            return context_data_str
        return json.dumps(ensure_json_safe(context_data_str), ensure_ascii=False)
