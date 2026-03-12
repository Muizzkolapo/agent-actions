"""Dataclasses for consistent metadata structure across processing pipelines."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ResponseMetadata:
    """Normalized metadata extracted from LLM responses across all providers."""

    model: Optional[str] = None
    finish_reason: Optional[str] = None
    status_code: Optional[int] = None
    provider: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    latency_ms: Optional[float] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, omitting None values."""
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
        """Create a ResponseMetadata from a dictionary."""
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
    """Top-level metadata container for output records."""

    response: Optional[ResponseMetadata] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with nested response metadata."""
        result: Dict[str, Any] = {}
        if self.response is not None:
            result["response"] = self.response.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedMetadata":
        """Create a UnifiedMetadata from a dictionary."""
        response = None
        if "response" in data:
            response = ResponseMetadata.from_dict(data["response"])
        return cls(response=response)
