"""Provider-agnostic metadata extraction from LLM responses."""

import time
from typing import Any

from .types import ResponseMetadata, UnifiedMetadata


class MetadataExtractor:
    """Extracts and normalizes metadata from LLM responses across providers."""

    # Provider name mappings for normalization
    PROVIDER_ALIASES: dict[str, str] = {
        "openai": "openai",
        "azure": "openai",
        "azure_openai": "openai",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "ollama": "ollama",
        "google": "google",
        "gemini": "google",
        "vertexai": "google",
        "cohere": "cohere",
        "mistral": "mistral",
        "tool": "tool",
    }

    @classmethod
    def extract_from_response(
        cls,
        response: Any,
        provider: str | None = None,
        model: str | None = None,
        latency_ms: float | None = None,
        agent_config: dict[str, Any] | None = None,
    ) -> ResponseMetadata:
        """Extract and normalize metadata from an LLM response."""
        normalized_provider = cls._normalize_provider(provider, agent_config)

        if response is None:
            return ResponseMetadata(
                provider=normalized_provider,
                model=model or cls._get_model_from_config(agent_config),
                latency_ms=latency_ms,
            )

        if isinstance(response, dict):
            return cls._extract_from_dict(
                response, normalized_provider, model, latency_ms, agent_config
            )

        return cls._extract_from_object(
            response, normalized_provider, model, latency_ms, agent_config
        )

    @classmethod
    def _extract_from_dict(
        cls,
        response: dict[str, Any],
        provider: str | None,
        model: str | None,
        latency_ms: float | None,
        agent_config: dict[str, Any] | None,
    ) -> ResponseMetadata:
        """Extract metadata from a dictionary response."""
        extracted_model = response.get("model") or model or cls._get_model_from_config(agent_config)
        finish_reason = response.get("finish_reason") or response.get("stop_reason")
        status_code = response.get("status_code") or response.get("http_status")
        request_id = response.get("request_id") or response.get("id")

        usage = cls._extract_usage(response)
        raw = cls._extract_raw_metadata(response, provider)

        return ResponseMetadata(
            model=extracted_model,
            finish_reason=finish_reason,
            status_code=status_code,
            provider=provider,
            usage=usage,
            latency_ms=latency_ms,
            request_id=request_id,
            raw=raw,
        )

    @classmethod
    def _extract_from_object(
        cls,
        response: Any,
        provider: str | None,
        model: str | None,
        latency_ms: float | None,
        agent_config: dict[str, Any] | None,
    ) -> ResponseMetadata:
        """Extract metadata from an SDK response object."""
        extracted_model = model or cls._get_model_from_config(agent_config)
        finish_reason = None
        status_code = None
        request_id = None
        usage = None
        raw: dict[str, Any] = {}

        if hasattr(response, "model"):
            extracted_model = response.model or extracted_model

        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "finish_reason"):
                finish_reason = choice.finish_reason

        if hasattr(response, "stop_reason"):
            finish_reason = response.stop_reason

        if hasattr(response, "status_code"):
            status_code = response.status_code
        elif hasattr(response, "http_status"):
            status_code = response.http_status

        if hasattr(response, "id"):
            request_id = response.id
        elif hasattr(response, "request_id"):
            request_id = response.request_id

        if hasattr(response, "usage") and response.usage:
            usage = cls._extract_usage_from_object(response.usage)

        return ResponseMetadata(
            model=extracted_model,
            finish_reason=finish_reason,
            status_code=status_code,
            provider=provider,
            usage=usage,
            latency_ms=latency_ms,
            request_id=request_id,
            raw=raw,
        )

    @classmethod
    def _extract_usage(cls, response: dict[str, Any]) -> dict[str, int] | None:
        """Extract token usage, normalizing OpenAI and Anthropic key names."""
        usage = response.get("usage")
        if not usage:
            return None

        if isinstance(usage, dict):
            # Use `in` checks rather than `or` to avoid treating 0 as falsy
            prompt = (
                usage.get("prompt_tokens")
                if "prompt_tokens" in usage
                else usage.get("input_tokens", 0)
            ) or 0  # guard against explicit None
            completion = (
                usage.get("completion_tokens")
                if "completion_tokens" in usage
                else usage.get("output_tokens", 0)
            ) or 0  # guard against explicit None
            total = usage.get("total_tokens") if "total_tokens" in usage else (prompt + completion)
            total = total or 0
            return {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
            }

        return None

    @classmethod
    def _extract_usage_from_object(cls, usage: Any) -> dict[str, int] | None:
        """Extract usage from an SDK usage object."""
        result: dict[str, int] = {}

        if hasattr(usage, "prompt_tokens"):
            result["prompt_tokens"] = usage.prompt_tokens or 0
        if hasattr(usage, "completion_tokens"):
            result["completion_tokens"] = usage.completion_tokens or 0
        if hasattr(usage, "total_tokens"):
            result["total_tokens"] = usage.total_tokens or 0
        elif "prompt_tokens" in result and "completion_tokens" in result:
            result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]

        if hasattr(usage, "input_tokens"):
            result["prompt_tokens"] = usage.input_tokens or 0
        if hasattr(usage, "output_tokens"):
            result["completion_tokens"] = usage.output_tokens or 0
            if "prompt_tokens" in result:
                result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]

        return result if result else None

    @classmethod
    def _extract_raw_metadata(
        cls, response: dict[str, Any], provider: str | None
    ) -> dict[str, Any]:
        """Extract provider-specific raw metadata."""
        raw: dict[str, Any] = {}

        if provider == "openai":
            if "system_fingerprint" in response:
                raw["system_fingerprint"] = response["system_fingerprint"]
            if "created" in response:
                raw["created"] = response["created"]

        if provider == "anthropic":
            if "type" in response:
                raw["type"] = response["type"]

        return raw

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
        return agent_config.get("model_name") or agent_config.get("model")

    @classmethod
    def build_unified_metadata(
        cls,
        response_metadata: ResponseMetadata | None = None,
    ) -> UnifiedMetadata:
        """Build a UnifiedMetadata container from response metadata."""
        return UnifiedMetadata(response=response_metadata)


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
