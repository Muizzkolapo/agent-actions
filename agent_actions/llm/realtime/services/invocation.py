"""Client invocation service for agent builder.

Handles client routing and invocation for different LLM providers.
"""

import importlib
import logging
import time
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
    "ollama_local": "ollama",
    "ollama_cloud": "ollama",
    "gemini": "google-genai",
}

# Client registry — external SDK providers use lazy "module:Class" strings
# so the CLI doesn't crash when an unused provider's SDK is absent or broken.
CLIENT_REGISTRY: dict[str, Any] = {
    "openai": "agent_actions.llm.providers.openai.client:OpenAIClient",
    "ollama_local": "agent_actions.llm.providers.ollama.client:OllamaLocalClient",
    "ollama_cloud": "agent_actions.llm.providers.ollama.client:OllamaCloudClient",
    "gemini": "agent_actions.llm.providers.gemini.client:GeminiClient",
    "cohere": "agent_actions.llm.providers.cohere.client:CohereClient",
    "anthropic": "agent_actions.llm.providers.anthropic.client:AnthropicClient",
    "groq": "agent_actions.llm.providers.groq.client:GroqClient",
    # Internal providers — no external SDK deps, safe to import eagerly.
    "tool": ToolClient,
    "agac-provider": AgacClient,
    "hitl": HitlClient,
}


def _resolve_client(model_vendor: str) -> Any:
    """Resolve provider client from registry, importing lazy entries on demand."""
    entry = CLIENT_REGISTRY[model_vendor]
    if isinstance(entry, str):
        module_path, class_name = entry.split(":", 1)
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
        except (ImportError, AttributeError) as err:
            from agent_actions.errors import DependencyError

            package = _VENDOR_PACKAGES.get(model_vendor, model_vendor)
            raise DependencyError(
                f"{model_vendor} provider requires the '{package}' package",
                context={
                    "client_type": model_vendor,
                    "package": package,
                    "install_command": f"uv pip install {package}",
                },
            ) from err
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
            ConfigurationError: If client is not supported
            DependencyError: If the provider's SDK package is not installed
        """
        if model_vendor not in CLIENT_REGISTRY:
            from agent_actions.errors import ConfigurationError

            raise ConfigurationError(
                f"Unsupported model vendor: {model_vendor}",
                context={
                    "model_vendor": model_vendor,
                    "supported_vendors": list(CLIENT_REGISTRY.keys()),
                },
            )

        client = _resolve_client(model_vendor)

        start = time.perf_counter()

        # Tool client has different parameters
        if model_vendor == "tool":
            result = client.invoke(
                agent_config, context_data, tool_args=tool_args, source_content=source_content
            )
        elif model_vendor == "hitl":
            # HITL client has same signature as tool client; wrap for List consistency
            result = [
                client.invoke(
                    agent_config, context_data, tool_args=tool_args, source_content=source_content
                )
            ]
        else:
            # Standard client invocation (all providers, including Groq)
            result = client.invoke(agent_config, prompt_config, context_data, schema)

        elapsed = time.perf_counter() - start
        logger.info(
            "LLM call completed: vendor=%s action=%s elapsed=%.3fs",
            model_vendor,
            action_name,
            elapsed,
        )

        return result  # type: ignore[no-any-return]
