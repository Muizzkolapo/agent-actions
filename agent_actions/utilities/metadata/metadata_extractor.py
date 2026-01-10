"""
Unified Metadata Extractor for batch and online modes.

This module provides a single source of truth for metadata extraction,
ensuring consistent output structure across all processing pipelines.
"""

import time
from typing import Any, Dict, Optional

from .metadata_types import ResponseMetadata, RetryMetadata, UnifiedMetadata


class MetadataExtractor:
    """
    Extracts and normalizes metadata from LLM responses.

    This service provides provider-agnostic metadata extraction that both
    batch and online modes use to ensure consistent output structure.

    Example:
        >>> extractor = MetadataExtractor()
        >>> metadata = extractor.extract_from_response(
        ...     response=llm_response,
        ...     provider="openai",
        ...     model="gpt-4"
        ... )
        >>> item["metadata"] = metadata.to_dict()
    """

    # Provider name mappings for normalization
    PROVIDER_ALIASES: Dict[str, str] = {
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
        provider: Optional[str] = None,
        model: Optional[str] = None,
        latency_ms: Optional[float] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> ResponseMetadata:
        """
        Extract metadata from an LLM response.

        Handles different response formats from various providers and
        normalizes them into a consistent ResponseMetadata structure.

        Args:
            response: The raw LLM response (dict, object, or None)
            provider: Provider name (e.g., 'openai', 'anthropic')
            model: Model name override (uses response data if not provided)
            latency_ms: Response latency in milliseconds
            agent_config: Agent configuration for additional context

        Returns:
            ResponseMetadata with extracted fields
        """
        # Normalize provider name
        normalized_provider = cls._normalize_provider(provider, agent_config)

        # Extract based on response type
        if response is None:
            return ResponseMetadata(
                provider=normalized_provider,
                model=model or cls._get_model_from_config(agent_config),
                latency_ms=latency_ms,
            )

        # Handle dict responses (most common for batch mode)
        if isinstance(response, dict):
            return cls._extract_from_dict(
                response, normalized_provider, model, latency_ms, agent_config
            )

        # Handle object responses (SDK response objects)
        return cls._extract_from_object(
            response, normalized_provider, model, latency_ms, agent_config
        )

    @classmethod
    def _extract_from_dict(
        cls,
        response: Dict[str, Any],
        provider: Optional[str],
        model: Optional[str],
        latency_ms: Optional[float],
        agent_config: Optional[Dict[str, Any]],
    ) -> ResponseMetadata:
        """Extract metadata from a dictionary response."""
        # Common fields across providers
        extracted_model = response.get("model") or model or cls._get_model_from_config(agent_config)
        finish_reason = response.get("finish_reason") or response.get("stop_reason")
        status_code = response.get("status_code") or response.get("http_status")
        request_id = response.get("request_id") or response.get("id")

        # Usage extraction (handle nested structures)
        usage = cls._extract_usage(response)

        # Provider-specific raw metadata
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
        provider: Optional[str],
        model: Optional[str],
        latency_ms: Optional[float],
        agent_config: Optional[Dict[str, Any]],
    ) -> ResponseMetadata:
        """Extract metadata from an SDK response object."""
        extracted_model = model or cls._get_model_from_config(agent_config)
        finish_reason = None
        status_code = None
        request_id = None
        usage = None
        raw: Dict[str, Any] = {}

        # Try common attribute names
        if hasattr(response, "model"):
            extracted_model = response.model or extracted_model

        # OpenAI-style response
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "finish_reason"):
                finish_reason = choice.finish_reason

        # Anthropic-style response
        if hasattr(response, "stop_reason"):
            finish_reason = response.stop_reason

        # Status code
        if hasattr(response, "status_code"):
            status_code = response.status_code
        elif hasattr(response, "http_status"):
            status_code = response.http_status

        # Request ID
        if hasattr(response, "id"):
            request_id = response.id
        elif hasattr(response, "request_id"):
            request_id = response.request_id

        # Usage
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
    def _extract_usage(cls, response: Dict[str, Any]) -> Optional[Dict[str, int]]:
        """Extract token usage information from response."""
        usage = response.get("usage")
        if not usage:
            return None

        if isinstance(usage, dict):
            return {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }

        return None

    @classmethod
    def _extract_usage_from_object(cls, usage: Any) -> Optional[Dict[str, int]]:
        """Extract usage from an SDK usage object."""
        result: Dict[str, int] = {}

        if hasattr(usage, "prompt_tokens"):
            result["prompt_tokens"] = usage.prompt_tokens or 0
        if hasattr(usage, "completion_tokens"):
            result["completion_tokens"] = usage.completion_tokens or 0
        if hasattr(usage, "total_tokens"):
            result["total_tokens"] = usage.total_tokens or 0
        elif "prompt_tokens" in result and "completion_tokens" in result:
            result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]

        # Anthropic-style usage
        if hasattr(usage, "input_tokens"):
            result["prompt_tokens"] = usage.input_tokens or 0
        if hasattr(usage, "output_tokens"):
            result["completion_tokens"] = usage.output_tokens or 0
            if "prompt_tokens" in result:
                result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]

        return result if result else None

    @classmethod
    def _extract_raw_metadata(
        cls, response: Dict[str, Any], provider: Optional[str]
    ) -> Dict[str, Any]:
        """Extract provider-specific raw metadata."""
        raw: Dict[str, Any] = {}

        # OpenAI-specific
        if provider == "openai":
            if "system_fingerprint" in response:
                raw["system_fingerprint"] = response["system_fingerprint"]
            if "created" in response:
                raw["created"] = response["created"]

        # Anthropic-specific
        if provider == "anthropic":
            if "type" in response:
                raw["type"] = response["type"]

        return raw

    @classmethod
    def _normalize_provider(
        cls, provider: Optional[str], agent_config: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """Normalize provider name to canonical form."""
        if provider:
            lower_provider = provider.lower()
            return cls.PROVIDER_ALIASES.get(lower_provider, lower_provider)

        # Try to get from agent_config
        if agent_config:
            model_vendor = agent_config.get("model_vendor", "")
            if model_vendor:
                lower_vendor = model_vendor.lower()
                return cls.PROVIDER_ALIASES.get(lower_vendor, lower_vendor)

        return None

    @classmethod
    def _get_model_from_config(cls, agent_config: Optional[Dict[str, Any]]) -> Optional[str]:
        """Get model name from agent configuration."""
        if not agent_config:
            return None
        return agent_config.get("model_name") or agent_config.get("model")

    @classmethod
    def build_retry_metadata(
        cls,
        was_retried: bool = False,
        retry_attempts: int = 0,
        original_batch_id: Optional[str] = None,
        final_batch_id: Optional[str] = None,
        retry_reason: Optional[str] = None,
    ) -> RetryMetadata:
        """
        Build retry metadata for a record.

        This method ensures consistent retry metadata structure across
        both batch and online modes.

        Args:
            was_retried: Whether this record required retry
            retry_attempts: Number of retry attempts
            original_batch_id: ID of the original batch (batch mode)
            final_batch_id: ID of the batch that succeeded (batch mode)
            retry_reason: Reason for retry if applicable

        Returns:
            RetryMetadata instance
        """
        return RetryMetadata(
            was_retried=was_retried,
            retry_attempts=retry_attempts,
            original_batch_id=original_batch_id,
            final_batch_id=final_batch_id,
            retry_reason=retry_reason,
        )

    @classmethod
    def build_unified_metadata(
        cls,
        response_metadata: Optional[ResponseMetadata] = None,
        retry_metadata: Optional[RetryMetadata] = None,
    ) -> UnifiedMetadata:
        """
        Build unified metadata container.

        Args:
            response_metadata: LLM response metadata
            retry_metadata: Retry tracking metadata

        Returns:
            UnifiedMetadata instance
        """
        return UnifiedMetadata(
            response=response_metadata,
            retry=retry_metadata,
        )


class MetadataTimer:
    """
    Context manager for tracking operation latency.

    Example:
        >>> with MetadataTimer() as timer:
        ...     result = llm.call(prompt)
        >>> metadata = MetadataExtractor.extract_from_response(
        ...     response=result,
        ...     latency_ms=timer.elapsed_ms
        ... )
    """

    def __init__(self):
        self._start_time: Optional[float] = None
        self._end_time: Optional[float] = None

    def __enter__(self) -> "MetadataTimer":
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, *args) -> None:
        self._end_time = time.perf_counter()

    @property
    def elapsed_ms(self) -> Optional[float]:
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
