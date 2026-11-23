"""Response metadata from an action's config."""

import time
from typing import Any

from .types import ResponseMetadata


class MetadataExtractor:
    """The provider and model of an action's responses, normalized."""

    # Provider name mappings for normalization
    PROVIDER_ALIASES: dict[str, str] = {
        "openai": "openai",
        "azure": "openai",
        "azure_openai": "openai",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "ollama_local": "ollama_local",
        "ollama_cloud": "ollama_cloud",
        "google": "google",
        "gemini": "google",
        "vertexai": "google",
        "cohere": "cohere",
        "tool": "tool",
    }

    @classmethod
    def from_config(cls, agent_config: dict[str, Any] | None) -> ResponseMetadata:
        """The provider and model an action's config names."""
        return ResponseMetadata(
            provider=cls._normalize_provider(None, agent_config),
            model=cls._get_model_from_config(agent_config),
        )

    @classmethod
    def _normalize_provider(
        cls, provider: str | None, agent_config: dict[str, Any] | None
    ) -> str | None:
        """Normalize provider name to canonical form."""
        if provider:
            lower_provider = provider.lower()
            return cls.PROVIDER_ALIASES.get(lower_provider, lower_provider)

        if agent_config:
            model_vendor = agent_config.get("model_vendor", "")
            if model_vendor:
                lower_vendor: str = model_vendor.lower()
                return cls.PROVIDER_ALIASES.get(lower_vendor, lower_vendor)

        return None

    @classmethod
    def _get_model_from_config(cls, agent_config: dict[str, Any] | None) -> str | None:
        """Get model name from agent configuration."""
        if not agent_config:
            return None
        return agent_config.get("model_name")


class MetadataTimer:
    """Context manager for tracking operation latency in milliseconds."""

    def __init__(self):
        self._start_time: float | None = None
        self._end_time: float | None = None

    def __enter__(self) -> "MetadataTimer":
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb) -> None:
        self._end_time = time.perf_counter()

    @property
    def elapsed_ms(self) -> float | None:
        """Get elapsed time in milliseconds."""
        if self._start_time is None:
            return None
        end = self._end_time or time.perf_counter()
        return (end - self._start_time) * 1000

    def start(self) -> None:
        """Manually start the timer."""
        self._start_time = time.perf_counter()
        self._end_time = None

    def stop(self) -> float:
        """Manually stop the timer and return elapsed ms."""
        self._end_time = time.perf_counter()
        return self.elapsed_ms or 0.0
