"""Client invocation service for agent builder.

Handles client routing and invocation for different LLM providers.
"""

import importlib
import logging
from typing import Any

from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.llm.providers.anthropic.client import AnthropicClient
from agent_actions.llm.providers.cohere.client import CohereClient
from agent_actions.llm.providers.groq.client import GroqClient
from agent_actions.llm.providers.hitl.client import HitlClient
from agent_actions.llm.providers.mistral.client import MistralClient
from agent_actions.llm.providers.ollama.client import OllamaClient
from agent_actions.llm.providers.openai.client import OpenAIClient
from agent_actions.llm.providers.tools.client import ToolClient

logger = logging.getLogger(__name__)

# Client registry
CLIENT_REGISTRY: dict[str, Any] = {
    "openai": OpenAIClient,
    "ollama": OllamaClient,
    # Lazy import avoids deprecated SDK warnings for non-Gemini commands.
    "gemini": "agent_actions.llm.providers.gemini.client:GeminiClient",
    "cohere": CohereClient,
    "mistral": MistralClient,
    "anthropic": AnthropicClient,
    "groq": GroqClient,
    "tool": ToolClient,
    "agac-provider": AgacClient,
    "hitl": HitlClient,
}

# All providers now normalise their return type to List[Dict] internally,
# so no wrapping is needed here.
SINGLE_RESPONSE_CLIENTS: set = set()


def _resolve_client(model_vendor: str) -> Any:
    """Resolve provider client from registry, importing lazy entries on demand."""
    entry = CLIENT_REGISTRY[model_vendor]
    if isinstance(entry, str):
        module_path, class_name = entry.split(":", 1)
        cls = getattr(importlib.import_module(module_path), class_name)
        CLIENT_REGISTRY[model_vendor] = cls
        return cls
    return entry


class ClientInvocationService:
    """Handles client routing and invocation for agents."""

    @staticmethod
    def invoke_client(
        model_vendor: str,
        agent_config: dict[str, Any],
        prompt_config: str,
        context_data: str | dict,
        schema: dict[str, Any] | None,
        granularity: str,
        formatted_prompt: str | None = None,
        tool_args: dict[str, Any] | None = None,
        source_content: Any | None = None,
        action_name: str | None = None,
    ) -> list[Any]:
        """
        Delegate to the specific client and normalize the response.

        Handles client-specific invocation patterns:
        - Tool: Uses tool_args and source_content
        - Others: Standard prompt_config and context_data

        Args:
            model_vendor: Client identifier (e.g., 'openai', 'anthropic')
            agent_config: Agent configuration
            prompt_config: Prepared prompt string
            context_data: Context data (str or dict)
            schema: Prepared schema (optional)
            granularity: Processing granularity ('record' or 'file')
            formatted_prompt: Pre-formatted prompt (unused, kept for API compat)
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

        client = _resolve_client(model_vendor)

        # Tool client has different parameters
        if model_vendor == "tool":
            return client.invoke(  # type: ignore[no-any-return]
                agent_config, context_data, tool_args=tool_args, source_content=source_content
            )

        # HITL client has same signature as tool client; wrap for List consistency
        if model_vendor == "hitl":
            result = client.invoke(
                agent_config, context_data, tool_args=tool_args, source_content=source_content
            )
            return [result]

        # Standard client invocation (all providers, including Groq)
        result = client.invoke(agent_config, prompt_config, context_data, schema)

        # Single-response clients return single item, wrap in list for consistency
        if model_vendor in SINGLE_RESPONSE_CLIENTS:
            result = [result]

        return result  # type: ignore[no-any-return]
