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
class RetryMetadata:
    """
    Metadata about retry attempts for a record.

    Tracks whether a record was retried and how many attempts were made.
    Used by both batch and online modes for consistent retry tracking.

    Attributes:
        was_retried: Whether this record required retry
        retry_attempts: Number of retry attempts (0 = succeeded on first try)
        error_type: Type of error that triggered retry (e.g., 'RateLimitError')
        error_message: Error message from the retry-triggering error
        exhausted: Whether all retry attempts were exhausted without success
        original_batch_id: ID of the original batch (batch mode only)
        final_batch_id: ID of the batch that succeeded (batch mode only)
        retry_reason: Reason for retry if applicable
    """

    was_retried: bool = False
    retry_attempts: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    exhausted: bool = False
    original_batch_id: Optional[str] = None
    final_batch_id: Optional[str] = None
    retry_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary representation of retry metadata.
        """
        result: Dict[str, Any] = {
            "was_retried": self.was_retried,
            "retry_attempts": self.retry_attempts,
        }
        if self.error_type is not None:
            result["error_type"] = self.error_type
        if self.error_message is not None:
            result["error_message"] = self.error_message
        if self.exhausted:
            result["exhausted"] = self.exhausted
        if self.original_batch_id is not None:
            result["original_batch_id"] = self.original_batch_id
        if self.final_batch_id is not None:
            result["final_batch_id"] = self.final_batch_id
        if self.retry_reason is not None:
            result["retry_reason"] = self.retry_reason
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryMetadata":
        """Create from dictionary.

        Args:
            data: Dictionary containing retry metadata fields

        Returns:
            RetryMetadata instance
        """
        return cls(
            was_retried=data.get("was_retried", False),
            retry_attempts=data.get("retry_attempts", 0),
            error_type=data.get("error_type"),
            error_message=data.get("error_message"),
            exhausted=data.get("exhausted", False),
            original_batch_id=data.get("original_batch_id"),
            final_batch_id=data.get("final_batch_id"),
            retry_reason=data.get("retry_reason"),
        )


@dataclass
class UnifiedMetadata:
    """
    Combined metadata container for output records.

    This is the top-level metadata structure added to each output record,
    ensuring consistency between batch and online modes.

    Attributes:
        response: LLM response metadata
        retry: Retry tracking metadata
    """

    response: Optional[ResponseMetadata] = None
    retry: Optional[RetryMetadata] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization.

        Returns:
            Dictionary with nested response and retry metadata.
        """
        result: Dict[str, Any] = {}
        if self.response is not None:
            result["response"] = self.response.to_dict()
        if self.retry is not None:
            result["retry"] = self.retry.to_dict()
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
        retry = None
        if "response" in data:
            response = ResponseMetadata.from_dict(data["response"])
        if "retry" in data:
            retry = RetryMetadata.from_dict(data["retry"])
        return cls(response=response, retry=retry)
