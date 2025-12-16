"""
Factory for creating batch providers based on configuration.
"""

from typing import Optional, Dict, Any
import os
from .base import BatchProvider
from .openai.provider import OpenAIBatchProvider
from .gemini.provider import GeminiBatchProvider
from .ollama.provider import OllamaLocalBatchProvider

try:
    from .anthropic.provider import AnthropicBatchProvider

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


class BatchProviderFactory:
    """
    Factory class for creating batch provider instances.

    This factory supports creating providers based on a provider type string,
    making it easy to switch between different batch processing backends.
    """

    @staticmethod
    def create_provider(
        provider_type: str = "openai", config: Optional[Dict[str, Any]] = None
    ) -> BatchProvider:
        """
        Create a batch provider instance.

        Args:
            provider_type: Type of provider to create ("openai", "gemini", etc.)
            config: Optional configuration dict with provider-specific settings

        Returns:
            BatchProvider instance

        Raises:
            ValueError: If provider_type is not recognized
        """
        config = config or {}
        provider_type = provider_type.lower()
        if provider_type == "openai":
            api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY")
            return OpenAIBatchProvider(api_key=api_key)
        elif provider_type == "gemini":
            api_key = config.get("api_key") or os.getenv("GOOGLE_API_KEY")
            try:
                return GeminiBatchProvider(api_key=api_key)
            except ImportError as e:
                from agent_actions.errors import DependencyError  # New modular pattern!

                raise DependencyError(
                    "GeminiBatchProvider", "google-genai", {
                        "provider_type": provider_type,
                        "install_command": "pip install google-genai",
                    },
                    cause=e,
                ) from e
        elif provider_type == "ollama":
            base_url = config.get("base_url") or os.getenv("OLLAMA_HOST", "http://localhost:11434")
            return OllamaLocalBatchProvider(base_url=base_url)
        elif provider_type == "anthropic":
            if not ANTHROPIC_AVAILABLE:
                from agent_actions.errors import DependencyError  # New modular pattern!

                raise DependencyError(
                    "AnthropicBatchProvider", "anthropic", {
                        "provider_type": provider_type,
                        "install_command": "pip install anthropic",
                    },
                )
            api_key = config.get("api_key") or os.getenv("CLAUDE_API_KEY")
            anthropic_version = config.get("anthropic_version")
            enable_prompt_caching = config.get("enable_prompt_caching", False)
            try:
                return AnthropicBatchProvider(
                    api_key=api_key,
                    version=anthropic_version,
                    enable_prompt_caching=enable_prompt_caching,
                )
            except ImportError as e:
                from agent_actions.errors import DependencyError  # New modular pattern!

                raise DependencyError(
                    "AnthropicBatchProvider", "anthropic", {
                        "provider_type": provider_type,
                        "install_command": "pip install anthropic",
                    },
                    cause=e,
                ) from e
        else:
            from agent_actions.errors import ConfigurationError  # New modular pattern!

            supported = BatchProviderFactory.get_supported_providers()
            raise ConfigurationError(
                "Unknown provider type",
                context={
                    "provider_type": provider_type,
                    "supported_providers": supported,
                    "suggestion": f"Set model_vendor to one of: {', '.join(supported)}. Check your agent configuration.",
                },
            )

    @staticmethod
    def get_supported_providers() -> list[str]:
        """Get list of supported provider types."""
        providers = ["openai", "gemini", "ollama"]
        if ANTHROPIC_AVAILABLE:
            providers.append("anthropic")
        return providers
