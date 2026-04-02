"""Client invocation service for agent builder.

Handles client routing and invocation for different LLM providers.
"""

import importlib
import logging
from typing import Any

from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.llm.providers.hitl.client import HitlClient
from agent_actions.llm.providers.tools.client import ToolClient

logger = logging.getLogger(__name__)

# Vendor → pip package name, used for actionable DependencyError messages.
_VENDOR_PACKAGES: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "cohere": "cohere",
    "groq": "groq",
    "ollama": "ollama",
    "gemini": "google-genai",
    "mistral": "mistralai",
}

# Client registry — external SDK providers use lazy "module:Class" strings
# so the CLI doesn't crash when an unused provider's SDK is absent or broken.
CLIENT_REGISTRY: dict[str, Any] = {
    "openai": "agent_actions.llm.providers.openai.client:OpenAIClient",
    "ollama": "agent_actions.llm.providers.ollama.client:OllamaClient",
    "gemini": "agent_actions.llm.providers.gemini.client:GeminiClient",
    "cohere": "agent_actions.llm.providers.cohere.client:CohereClient",
    "mistral": "agent_actions.llm.providers.mistral.client:MistralClient",
    "anthropic": "agent_actions.llm.providers.anthropic.client:AnthropicClient",
    "groq": "agent_actions.llm.providers.groq.client:GroqClient",
    # Internal providers — no external SDK deps, safe to import eagerly.
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
        try:
            cls = getattr(importlib.import_module(module_path), class_name)
        except ImportError:
            from agent_actions.errors import DependencyError

            package = _VENDOR_PACKAGES.get(model_vendor, model_vendor)
            raise DependencyError(
                f"{model_vendor} provider requires the '{package}' package",
                context={
                    "client_type": model_vendor,
                    "package": package,
                    "install_command": f"uv pip install {package}",
                },
            ) from None
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
