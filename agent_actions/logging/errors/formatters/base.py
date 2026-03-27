"""Base error formatter interface for Strategy Pattern."""

from abc import ABC, abstractmethod
from typing import Any

from ..user_error import UserError


class ErrorFormatter(ABC):
    """Base error formatter strategy for a specific error category."""

    @abstractmethod
    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        """Return True if this formatter can handle the given error."""

    @abstractmethod
    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
        """Format the error into a user-friendly UserError."""

    def _extract_provider_name(self, message: str, context: dict[str, Any]) -> str:
        """Extract provider name from error message or context, defaulting to 'API'."""
        message_lower = message.lower()

        if "anthropic" in message_lower:
            return "anthropic"
        if "openai" in message_lower:
            return "openai"
        if "gemini" in message_lower:
            return "gemini"
        if "cohere" in message_lower:
            return "cohere"

        return str(context.get("provider", "API"))
