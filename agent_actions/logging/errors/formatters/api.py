"""API and network error formatter."""

from typing import Any

from ..user_error import UserError
from .base import ErrorFormatter


class APIErrorFormatter(ErrorFormatter):
    """Handles API/network errors."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        exc_names = [type(exc).__name__, type(root).__name__]

        if any(name.endswith("APIError") or "API" in name for name in exc_names):
            return True
        if any(name in ["NetworkError", "ConnectionError", "TimeoutError"] for name in exc_names):
            return True

        message_lower = message.lower()
        api_patterns = [
            "api",
            "connection",
            "network",
            "timeout",
            "request failed",
            "service unavailable",
            "rate limit",
        ]
        return any(pattern in message_lower for pattern in api_patterns)

    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
        provider = self._extract_provider_name(message, context)

        if "rate limit" in message.lower():
            return UserError(
                category="API Error",
                title="Rate limit exceeded",
                details=f"Too many requests to {provider.title()} API",
                fix="Wait a few minutes before trying again, or upgrade your API plan",
                context=context,
            )

        if "timeout" in message.lower() or "connection" in message.lower():
            return UserError(
                category="Network Error",
                title="Connection failed",
                details=f"Could not connect to {provider.title()} API",
                fix="Check your internet connection and try again",
                context=context,
            )

        return UserError(
            category="API Error",
            title=f"{provider.title()} API error",
            details=message,
            fix="Check your API key and network connection",
            context=context,
        )
