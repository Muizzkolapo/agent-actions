"""
Factory for creating batch clients based on configuration.

Uses a registry pattern to map vendor names to client constructors,
replacing the previous if/elif chain.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable, Tuple

from .batch_base import BaseBatchClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BatchClientRegistration:
    """Registry entry for a batch client vendor."""

    factory: Callable[[Dict[str, Any]], BaseBatchClient]
    package: Optional[str] = None
    aliases: Tuple[str, ...] = ()


def _try_import(module_path: str, class_name: str):
    """Attempt to import a batch client class, returning (cls, True) or (None, False)."""
    try:
        import importlib

        mod = importlib.import_module(module_path, package=__package__)
        return getattr(mod, class_name), True
    except ImportError:
        return None, False


def _is_package_available(package: str) -> bool:
    """Check if a Python package is importable without executing it."""
    import importlib.util

    return importlib.util.find_spec(package) is not None


def _require_class(cls, available: bool, client_type: str, package: str):
    """Raise DependencyError if a vendor SDK is not installed."""
    if not available:
        from agent_actions.errors import DependencyError

        raise DependencyError(
            f"{client_type} batch client requires {package} package",
            context={
                "client_type": client_type,
                "package": package,
                "install_command": f"uv pip install {package}",
            },
        )
    return cls


# --- Vendor factory functions ---


def _create_openai(config: Dict[str, Any]) -> BaseBatchClient:
    from .openai.batch_client import OpenAIBatchClient

    api_key = config.get("api_key") or os.getenv("OPENAI_API_KEY")
    return OpenAIBatchClient(api_key=api_key)


def _create_gemini(config: Dict[str, Any]) -> BaseBatchClient:
    cls, available = _try_import(".gemini.batch_client", "GeminiBatchClient")
    cls = _require_class(cls, available, "gemini", "google-genai")
    api_key = config.get("api_key") or os.getenv("GEMINI_API_KEY")
    return cls(api_key=api_key)


def _create_ollama(config: Dict[str, Any]) -> BaseBatchClient:
    from .ollama.batch_client import OllamaBatchClient

    base_url = config.get("base_url") or os.getenv("OLLAMA_HOST", "http://localhost:11434")
    return OllamaBatchClient(base_url=base_url)


def _create_anthropic(config: Dict[str, Any]) -> BaseBatchClient:
    cls, available = _try_import(".anthropic.batch_client", "AnthropicBatchClient")
    cls = _require_class(cls, available, "anthropic", "anthropic")
    api_key = config.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
    return cls(
        api_key=api_key,
        version=config.get("anthropic_version"),
        enable_prompt_caching=config.get("enable_prompt_caching", False),
    )


def _create_groq(config: Dict[str, Any]) -> BaseBatchClient:
    cls, available = _try_import(".groq.batch_client", "GroqBatchClient")
    cls = _require_class(cls, available, "groq", "groq")
    api_key = config.get("api_key") or os.getenv("GROQ_API_KEY")
    return cls(api_key=api_key)


def _create_mistral(config: Dict[str, Any]) -> BaseBatchClient:
    cls, available = _try_import(".mistral.batch_client", "MistralBatchClient")
    cls = _require_class(cls, available, "mistral", "mistralai")
    api_key = config.get("api_key") or os.getenv("MISTRAL_API_KEY")
    return cls(api_key=api_key)


def _create_agac(config: Dict[str, Any]) -> BaseBatchClient:
    from .agac.batch_client import AgacBatchClient

    polls_until_complete = config.get("polls_until_complete")
    return AgacBatchClient(polls_until_complete=polls_until_complete)


# --- Registry ---

_BATCH_CLIENT_REGISTRY: Dict[str, _BatchClientRegistration] = {
    "openai": _BatchClientRegistration(factory=_create_openai),
    "gemini": _BatchClientRegistration(factory=_create_gemini, package="google-genai"),
    "ollama": _BatchClientRegistration(factory=_create_ollama),
    "anthropic": _BatchClientRegistration(factory=_create_anthropic, package="anthropic"),
    "groq": _BatchClientRegistration(factory=_create_groq, package="groq"),
    "mistral": _BatchClientRegistration(factory=_create_mistral, package="mistralai"),
    "agac-provider": _BatchClientRegistration(factory=_create_agac, aliases=("mock",)),
}

# Build reverse alias map
_ALIAS_MAP: Dict[str, str] = {}
for _name, _reg in _BATCH_CLIENT_REGISTRY.items():
    for _alias in _reg.aliases:
        _ALIAS_MAP[_alias] = _name


class BatchClientFactory:
    """
    Factory class for creating batch client instances.

    Uses a registry pattern to map vendor names to client constructors.
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
            ConfigurationError: If client_type is not recognized
        """
        config = config or {}
        key = client_type.lower()

        # Resolve aliases (e.g., "mock" -> "agac-provider")
        key = _ALIAS_MAP.get(key, key)

        registration = _BATCH_CLIENT_REGISTRY.get(key)
        if registration is None:
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

        return registration.factory(config)

    @staticmethod
    def get_supported_clients() -> list[str]:
        """Get list of supported client types."""
        supported = []
        for name, reg in _BATCH_CLIENT_REGISTRY.items():
            if reg.package is None:
                supported.append(name)
            elif _is_package_available(reg.package):
                supported.append(name)
        return supported
