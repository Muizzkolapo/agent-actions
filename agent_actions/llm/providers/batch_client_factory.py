"""
Factory for creating batch clients based on configuration.
"""

from typing import Optional, Dict, Any
import os
from .batch_base import BaseBatchClient
from .openai.batch_client import OpenAIBatchClient
from .gemini.batch_client import GeminiBatchClient
from .ollama.batch_client import OllamaBatchClient

try:
    from .anthropic.batch_client import AnthropicBatchClient

    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from .groq.batch_client import GroqBatchClient

    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    from .mistral.batch_client import MistralBatchClient

    MISTRAL_AVAILABLE = True
except ImportError:
    MISTRAL_AVAILABLE = False

# Agac mock client is always available (for testing)
from .agac.batch_client import AgacBatchClient


class BatchClientFactory:
    """
    Factory class for creating batch client instances.

    This factory supports creating clients based on a client type string,
    making it easy to switch between different batch processing backends.
    """

    @staticmethod
    def create_client(
        client_type: str = "openai", config: Optional[Dict[str, Any]] = None
    ) -> BaseBatchClient:
        """
        Create a batch client instance.

        Args:
            client_type: Type of client to create ("openai", "gemini", etc.)
            config: Optional configuration dict with client-specific settings

        Returns:
            BaseBatchClient instance

        Raises:
            ValueError: If client_type is not recognized
        """
        config = config or {}
        client_type = client_type.lower()
        if client_type == "openai":
            api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY")
            return OpenAIBatchClient(api_key=api_key)
        if client_type == "gemini":
            api_key = config.get("api_key") or os.getenv("GEMINI_API_KEY")
            try:
                return GeminiBatchClient(api_key=api_key)
            except ImportError as e:
                from agent_actions.errors import DependencyError

                raise DependencyError(
                    "GeminiBatchClient requires google-genai package",
                    context={
                        "client_type": client_type,
                        "package": "google-genai",
                        "install_command": "pip install google-genai",
                    },
                    cause=e,
                ) from e
        if client_type == "ollama":
            base_url = config.get("base_url") or os.getenv("OLLAMA_HOST", "http://localhost:11434")
            return OllamaBatchClient(base_url=base_url)
        if client_type == "anthropic":
            if not ANTHROPIC_AVAILABLE:
                from agent_actions.errors import DependencyError

                raise DependencyError(
                    "AnthropicBatchClient requires anthropic package",
                    context={
                        "client_type": client_type,
                        "package": "anthropic",
                        "install_command": "pip install anthropic",
                    },
                )
            api_key = config.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
            anthropic_version = config.get("anthropic_version")
            enable_prompt_caching = config.get("enable_prompt_caching", False)
            try:
                return AnthropicBatchClient(
                    api_key=api_key,
                    version=anthropic_version,
                    enable_prompt_caching=enable_prompt_caching,
                )
            except ImportError as e:
                from agent_actions.errors import DependencyError

                raise DependencyError(
                    "AnthropicBatchClient requires anthropic package",
                    context={
                        "client_type": client_type,
                        "package": "anthropic",
                        "install_command": "pip install anthropic",
                    },
                    cause=e,
                ) from e

        if client_type == "groq":
            if not GROQ_AVAILABLE:
                from agent_actions.errors import DependencyError

                raise DependencyError(
                    "GroqBatchClient requires groq package",
                    context={
                        "client_type": client_type,
                        "package": "groq",
                        "install_command": "pip install groq",
                    },
                )
            api_key = config.get("api_key") or os.getenv("GROQ_API_KEY")
            return GroqBatchClient(api_key=api_key)

        if client_type == "mistral":
            if not MISTRAL_AVAILABLE:
                from agent_actions.errors import DependencyError

                raise DependencyError(
                    "MistralBatchClient requires mistralai package",
                    context={
                        "client_type": client_type,
                        "package": "mistralai",
                        "install_command": "pip install mistralai",
                    },
                )
            api_key = config.get("api_key") or os.getenv("MISTRAL_API_KEY")
            return MistralBatchClient(api_key=api_key)

        if client_type == "mock" or client_type == "agac-provider":
            # Agac mock client for testing batch processing without hitting real APIs
            polls_until_complete = config.get("polls_until_complete")
            return AgacBatchClient(polls_until_complete=polls_until_complete)

        from agent_actions.errors import ConfigurationError

        supported = BatchClientFactory.get_supported_clients()
        raise ConfigurationError(
            "Unknown client type",
            context={
                "client_type": client_type,
                "supported_clients": supported,
                "suggestion": (
                    f"Set model_vendor to one of: {', '.join(supported)}. "
                    "Check your agent configuration."
                ),
            },
        )

    @staticmethod
    def get_supported_clients() -> list[str]:
        """Get list of supported client types."""
        clients = ["openai", "gemini", "ollama", "agac-provider"]
        if ANTHROPIC_AVAILABLE:
            clients.append("anthropic")
        if GROQ_AVAILABLE:
            clients.append("groq")
        if MISTRAL_AVAILABLE:
            clients.append("mistral")
        return clients
