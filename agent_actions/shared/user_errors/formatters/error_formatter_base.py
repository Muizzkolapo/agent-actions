"""Base error formatter interface for Strategy Pattern."""

from abc import ABC, abstractmethod
from typing import Dict, Any
from ..user_error import UserError


class ErrorFormatter(ABC):
    """
    Base error formatter strategy.

    Each concrete formatter handles a specific category of errors
    (Configuration, Model, Authentication, File, API, etc.).
    """

    @abstractmethod
    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        """
        Determine if this formatter can handle the given error.

        Args:
            exc: The original exception
            root: The root cause exception
            message: The root cause error message

        Returns:
            True if this formatter should handle the error
        """

    @abstractmethod
    def format(
        self,
        exc: Exception,
        root: Exception,
        message: str,
        context: Dict[str, Any]
    ) -> UserError:
        """
        Format the error into a user-friendly UserError.

        Args:
            exc: The original exception
            root: The root cause exception
            message: The root cause error message
            context: Additional context (agent, file_path, etc.)

        Returns:
            UserError with user-friendly message
        """

    def _extract_provider_name(self, message: str, context: Dict[str, Any]) -> str:
        """
        Extract provider name from error message or context.

        Checks message for common provider names (anthropic, openai, gemini, cohere)
        and falls back to context['provider'] or 'API'.

        Args:
            message: Error message to search
            context: Context dict that may contain 'provider' key

        Returns:
            Provider name (lowercase) or 'API' as fallback
        """
        message_lower = message.lower()

        if 'anthropic' in message_lower:
            return 'anthropic'
        if 'openai' in message_lower:
            return 'openai'
        if 'gemini' in message_lower:
            return 'gemini'
        if 'cohere' in message_lower:
            return 'cohere'

        return context.get('provider', 'API')
