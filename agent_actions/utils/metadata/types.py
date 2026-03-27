"""Dataclasses for consistent metadata structure across processing pipelines."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResponseMetadata:
    """Normalized metadata extracted from LLM responses across all providers."""

    model: str | None = None
    finish_reason: str | None = None
    status_code: int | None = None
    provider: str | None = None
    usage: dict[str, int] | None = None
    latency_ms: float | None = None
    request_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, omitting None values."""
        result: dict[str, Any] = {}
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
    def from_dict(cls, data: dict[str, Any]) -> "ResponseMetadata":
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

    response: ResponseMetadata | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with nested response metadata."""
        result: dict[str, Any] = {}
        if self.response is not None:
            result["response"] = self.response.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UnifiedMetadata":
        """Create a UnifiedMetadata from a dictionary."""
        response = None
        if "response" in data:
            response = ResponseMetadata.from_dict(data["response"])
        return cls(response=response)
