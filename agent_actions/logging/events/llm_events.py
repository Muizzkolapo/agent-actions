"""LLM interaction and template events (L/T prefixes)."""

from dataclasses import dataclass, field

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.events.types import EventCategories

__all__ = [
    "LLMRequestEvent",
    "LLMResponseEvent",
    "LLMErrorEvent",
    "RateLimitEvent",
    "TemplateRenderingFailedEvent",
    "TemplateSyntaxErrorEvent",
    "LLMJSONParseErrorEvent",
    "LLMConnectionErrorEvent",
    "LLMServerErrorEvent",
]


@dataclass
class LLMRequestEvent(BaseEvent):
    """Fired when an LLM request is made."""

    provider: str = ""
    model: str = ""
    action_name: str = ""
    prompt_tokens: int = 0
    request_id: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.LLM
        self.message = (
            f"LLM request to {self.provider}/{self.model} ({self.prompt_tokens} prompt tokens)"
        )
        self.data = {
            "provider": self.provider,
            "model": self.model,
            "action_name": self.action_name,
            "prompt_tokens": self.prompt_tokens,
            "request_id": self.request_id,
        }

    @property
    def code(self) -> str:
        return "L001"


@dataclass
class LLMResponseEvent(BaseEvent):
    """Fired when an LLM response is received."""

    provider: str = ""
    model: str = ""
    action_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    request_id: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.LLM
        self.message = f"LLM response: {self.total_tokens} tokens in {self.latency_ms:.0f}ms"
        self.data = {
            "provider": self.provider,
            "model": self.model,
            "action_name": self.action_name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
        }

    @property
    def code(self) -> str:
        return "L002"


@dataclass
class LLMErrorEvent(BaseEvent):
    """Fired when an LLM request fails."""

    provider: str = ""
    model: str = ""
    action_name: str = ""
    error_message: str = ""
    error_type: str = ""
    retry_count: int = 0
    request_id: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.LLM
        self.message = f"LLM error ({self.provider}/{self.model}): {self.error_message}"
        self.data = {
            "provider": self.provider,
            "model": self.model,
            "action_name": self.action_name,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "retry_count": self.retry_count,
            "request_id": self.request_id,
        }

    @property
    def code(self) -> str:
        return "L003"


@dataclass
class RateLimitEvent(BaseEvent):
    """Fired when a rate limit is hit."""

    provider: str = ""
    retry_after: float = 0.0
    action_name: str = ""
    request_id: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.LLM
        self.message = f"Rate limit hit ({self.provider}), retrying in {self.retry_after:.1f}s"
        self.data = {
            "provider": self.provider,
            "retry_after": self.retry_after,
            "action_name": self.action_name,
            "request_id": self.request_id,
        }

    @property
    def code(self) -> str:
        return "L004"


@dataclass
class TemplateRenderingFailedEvent(BaseEvent):
    """Fired when template rendering fails due to undefined variables."""

    action_name: str = ""
    missing_variables: list[str] = field(default_factory=list)
    error_message: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.TEMPLATE
        vars_str = ", ".join(self.missing_variables) if self.missing_variables else "unknown"
        self.message = (
            f"Template for '{self.action_name}' references undefined variables: {vars_str}"
        )
        self.data = {
            "action_name": self.action_name,
            "missing_variables": self.missing_variables,
            "error_message": self.error_message,
        }

    @property
    def code(self) -> str:
        return "T001"


@dataclass
class TemplateSyntaxErrorEvent(BaseEvent):
    """Fired when template has syntax errors."""

    action_name: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.TEMPLATE
        self.message = f"Template syntax error in '{self.action_name}': {self.error}"
        self.data = {
            "action_name": self.action_name,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "T002"


@dataclass
class LLMJSONParseErrorEvent(BaseEvent):
    """Fired when LLM returns unparseable JSON."""

    provider: str = ""
    model: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.LLM
        self.message = f"{self.provider}/{self.model} returned invalid JSON: {self.error}"
        self.data = {
            "provider": self.provider,
            "model": self.model,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "L005"


@dataclass
class LLMConnectionErrorEvent(BaseEvent):
    """Fired when LLM connection/timeout error occurs."""

    provider: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.LLM
        self.message = f"{self.provider} connection error: {self.error}"
        self.data = {
            "provider": self.provider,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "L006"


@dataclass
class LLMServerErrorEvent(BaseEvent):
    """Fired when LLM server error (5xx) occurs."""

    provider: str = ""
    status_code: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.LLM
        self.message = f"{self.provider} server error ({self.status_code}): {self.error}"
        self.data = {
            "provider": self.provider,
            "status_code": self.status_code,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "L007"
