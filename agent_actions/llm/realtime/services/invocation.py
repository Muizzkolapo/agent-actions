"""Client invocation service for agent builder.

Handles client routing and invocation for different LLM providers.
"""

import logging
from typing import Dict, Any, Optional, List, Union

from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.llm.providers.ollama.client import OllamaClient
from agent_actions.llm.providers.gemini.client import GeminiClient
from agent_actions.llm.providers.cohere.client import CohereClient
from agent_actions.llm.providers.mistral.client import MistralClient
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.groq.client import GroqClient
from agent_actions.llm.providers.tools.client import ToolClient
from agent_actions.llm.providers.agac.client import AgacClient

logger = logging.getLogger(__name__)

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
    "agac-provider": AgacClient,
}

# All providers now normalise their return type to List[Dict] internally,
# so no wrapping is needed here.
SINGLE_RESPONSE_CLIENTS: set = set()


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
        action_name: Optional[str] = None,
    ) -> List[Any]:
        """
        Delegate to the specific client and normalize the response.

        Handles client-specific invocation patterns:
        - Groq: Uses formatted_prompt parameter
        - Tool: Uses tool_args and source_content
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
            action_name: Action name for logging (optional)

        Returns:
            List of response data from the LLM

        Raises:
            ValueError: If client is not supported
        """
        if model_vendor not in CLIENT_REGISTRY:
            raise ValueError(f"Unsupported model vendor: {model_vendor}")

        client = CLIENT_REGISTRY[model_vendor]

        # Tool client has different parameters
        if model_vendor == "tool":
            return client.invoke(
                agent_config, context_data, tool_args=tool_args, source_content=source_content
            )

        # Groq client has special invocation signature
        if model_vendor == "groq":
            result = client.invoke(agent_config, formatted_prompt, context_data, schema)
        else:
            # Standard client invocation
            result = client.invoke(agent_config, prompt_config, context_data, schema)

        # Single-response clients return single item, wrap in list for consistency
        if model_vendor in SINGLE_RESPONSE_CLIENTS:
            result = [result]

        return result
