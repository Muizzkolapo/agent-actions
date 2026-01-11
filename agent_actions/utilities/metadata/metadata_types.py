"""
Unified metadata types for batch and online modes.

This module provides dataclasses that ensure consistent metadata structure
across both batch and online processing pipelines.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ResponseMetadata:
    """
    Metadata extracted from LLM responses.

    This provides consistent metadata structure across all providers
    (OpenAI, Anthropic, Ollama, etc.) and both batch/online modes.

    Attributes:
        model: The model used for generation (e.g., 'gpt-4', 'claude-3')
        finish_reason: Why the generation stopped ('stop', 'length', 'tool_calls', etc.)
        status_code: HTTP status code from the API response (if available)
        provider: The LLM provider name (e.g., 'openai', 'anthropic', 'ollama')
        usage: Token usage information (prompt_tokens, completion_tokens, total_tokens)
        latency_ms: Response latency in milliseconds (if tracked)
        request_id: Provider's request ID for debugging (if available)
        raw: Additional provider-specific metadata
    """

    model: Optional[str] = None
    finish_reason: Optional[str] = None
    status_code: Optional[int] = None
    provider: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    latency_ms: Optional[float] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with non-None values only.
        """
        result: Dict[str, Any] = {}
        if self.model is not None:
            result["model"] = self.model
        if self.finish_reason is not None:
            result["finish_reason"] = self.finish_reason
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.provider is not None:
            result["provider"] = self.provider
        if self.usage is not None:
            result["usage"] = self.usage
        if self.latency_ms is not None:
            result["latency_ms"] = self.latency_ms
        if self.request_id is not None:
            result["request_id"] = self.request_id
        if self.raw:
            result["raw"] = self.raw
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResponseMetadata":
        """Create from dictionary.

        Args:
            data: Dictionary containing metadata fields

        Returns:
            ResponseMetadata instance
        """
        return cls(
            model=data.get("model"),
            finish_reason=data.get("finish_reason"),
            status_code=data.get("status_code"),
            provider=data.get("provider"),
            usage=data.get("usage"),
            latency_ms=data.get("latency_ms"),
            request_id=data.get("request_id"),
            raw=data.get("raw", {}),
        )


@dataclass
class UnifiedMetadata:
    """
    Combined metadata container for output records.

    This is the top-level metadata structure added to each output record,
    ensuring consistency between batch and online modes.

    Attributes:
        response: LLM response metadata
    """

    response: Optional[ResponseMetadata] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with nested response metadata.
        """
        result: Dict[str, Any] = {}
        if self.response is not None:
            result["response"] = self.response.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedMetadata":
        """Create from dictionary.

        Args:
            data: Dictionary containing unified metadata

        Returns:
            UnifiedMetadata instance
        """
        response = None
        if "response" in data:
            response = ResponseMetadata.from_dict(data["response"])
        return cls(response=response)
