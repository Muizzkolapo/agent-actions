"""Client invocation service for agent builder."""

from typing import Dict, Any, Optional, List, Union
from agent_actions.llm_invocation.providers.openai.client import OpenAIClient
from agent_actions.llm_invocation.providers.ollama.client import OllamaClient
from agent_actions.llm_invocation.providers.gemini.client import GeminiClient
from agent_actions.llm_invocation.providers.cohere.client import CohereClient
from agent_actions.llm_invocation.providers.mistral.client import MistralClient
from agent_actions.llm_invocation.providers.anthropic.client import AnthropicClient
from agent_actions.llm_invocation.providers.groq.client import GroqClient
from agent_actions.llm_invocation.providers.tools.client import ToolClient


# Client registry
CLIENT_REGISTRY: Dict[str, Any] = {
    "openai": OpenAIClient,
    "ollama": OllamaClient,
    "gemini": GeminiClient,
    "cohere": CohereClient,
    "mistral": MistralClient,
    "anthropic": AnthropicClient,
    "groq": GroqClient,
    "tool": ToolClient,
}

# Clients that return single response (need wrapping in list)
SINGLE_RESPONSE_CLIENTS: set = {"cohere", "mistral", "anthropic", "groq"}


class ClientInvocationService:
    """Handles client routing and invocation for agents."""

    @staticmethod
    def invoke_client(
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
        Delegate to the specific client and normalize the response.

        Handles client-specific invocation patterns:
        - Groq: Uses formatted_prompt parameter
        - Tool: Uses tool_args and source_content, early return for file granularity
        - Others: Standard prompt_config and context_data

        Args:
            model_vendor: Client identifier (e.g., 'openai', 'anthropic')
            agent_config: Agent configuration
            prompt_config: Prepared prompt string
            context_data: Context data (str or dict)
            schema: Prepared schema (optional)
            granularity: Processing granularity ('record' or 'file')
            formatted_prompt: Pre-formatted prompt for groq (optional)
            tool_args: Tool arguments (optional)
            source_content: Source content for tool client (optional)

        Returns:
            List of response items from the client

        Raises:
            ValueError: If client is not supported
        """
        if model_vendor not in CLIENT_REGISTRY:
            raise ValueError(f"Unsupported model vendor: {model_vendor}")

        client = CLIENT_REGISTRY[model_vendor]

        # Groq client has special invocation signature
        if model_vendor == "groq":
            response_data = client.invoke(agent_config, formatted_prompt, context_data, schema)

        # Tool client has different parameters and early return for file granularity
        elif model_vendor == "tool":
            response_data = client.invoke(
                agent_config, context_data, tool_args=tool_args, source_content=source_content
            )
            # Tool client with file granularity returns immediately
            if granularity == "file":
                return response_data

        # Standard client invocation
        else:
            response_data = client.invoke(agent_config, prompt_config, context_data, schema)

        # Single-response clients return single item, wrap in list for consistency
        if model_vendor in SINGLE_RESPONSE_CLIENTS:
            return [response_data]

        return response_data
