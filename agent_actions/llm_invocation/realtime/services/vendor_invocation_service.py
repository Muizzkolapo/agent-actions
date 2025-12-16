"""Vendor invocation service for agent builder."""

from typing import Dict, Any, Optional, List, Union
from agent_actions.llm_invocation.providers.openai.vendor import OpenAIHandler
from agent_actions.llm_invocation.providers.ollama.vendor import OllamaHandler
from agent_actions.llm_invocation.providers.gemini.vendor import GeminiHandler
from agent_actions.llm_invocation.providers.cohere.vendor import CohereHandler
from agent_actions.llm_invocation.providers.mistral.vendor import MistralHandler
from agent_actions.llm_invocation.providers.anthropic.vendor import ClaudeHandler
from agent_actions.llm_invocation.providers.groq.vendor import GroqLlama3Handler
from agent_actions.llm_invocation.providers.deepseek.vendor import DeepSeekHandler
from agent_actions.llm_invocation.providers.tools.vendor import ToolHandler


# Vendor handler registry
VENDOR_HANDLERS: Dict[str, Any] = {
    "openai": OpenAIHandler,
    "ollama": OllamaHandler,
    "gemini": GeminiHandler,
    "cohere": CohereHandler,
    "mistral": MistralHandler,
    "anthropic": ClaudeHandler,
    "groq": GroqLlama3Handler,
    "deepseek": DeepSeekHandler,
    "tool": ToolHandler,
}

# Vendors that return single response (need wrapping in list)
SINGLE_RESPONSE_VENDORS: set = {"cohere", "mistral", "anthropic", "groq", "deepseek"}


class VendorInvocationService:
    """Handles vendor routing and invocation for agents."""

    @staticmethod
    def invoke_vendor(
        model_vendor: str,
        agent_config: Dict[str, Any],
        prompt_config: str,
        context_data: Union[str, Dict],
        schema: Optional[Dict[str, Any]],
        granularity: str,
        formatted_prompt: Optional[str] = None,
        tool_args: Optional[Dict[str, Any]] = None,
        source_content: Optional[Any] = None,
    ) -> List[Any]:
        """
        Delegate to the specific vendor handler and normalize the response.

        Handles vendor-specific invocation patterns:
        - Groq: Uses formatted_prompt parameter
        - Tool: Uses tool_args and source_content, early return for file granularity
        - Others: Standard prompt_config and context_data

        Args:
            model_vendor: Vendor identifier (e.g., 'openai', 'anthropic')
            agent_config: Agent configuration
            prompt_config: Prepared prompt string
            context_data: Context data (str or dict)
            schema: Prepared schema (optional)
            granularity: Processing granularity ('record' or 'file')
            formatted_prompt: Pre-formatted prompt for groq (optional)
            tool_args: Tool arguments (optional)
            source_content: Source content for tool handler (optional)

        Returns:
            List of response items from the vendor

        Raises:
            ValueError: If vendor is not supported
        """
        if model_vendor not in VENDOR_HANDLERS:
            raise ValueError(f"Unsupported model vendor: {model_vendor}")

        handler = VENDOR_HANDLERS[model_vendor]

        # Groq vendor has special invocation signature
        if model_vendor == "groq":
            response_data = handler.invoke(agent_config, formatted_prompt, context_data, schema)

        # Tool vendor has different parameters and early return for file granularity
        elif model_vendor == "tool":
            response_data = handler.invoke(
                agent_config, context_data, tool_args=tool_args, source_content=source_content
            )
            # Tool handler with file granularity returns immediately
            if granularity == "file":
                return response_data

        # Standard vendor invocation
        else:
            response_data = handler.invoke(agent_config, prompt_config, context_data, schema)

        # Single-response vendors return single item, wrap in list for consistency
        if model_vendor in SINGLE_RESPONSE_VENDORS:
            return [response_data]

        return response_data
