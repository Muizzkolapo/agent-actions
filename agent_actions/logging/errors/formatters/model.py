"""Model validation error formatter."""

import re
from typing import Any

from ..user_error import UserError
from .base import ErrorFormatter


class ModelErrorFormatter(ErrorFormatter):
    """Handles model validation errors."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        message_lower = message.lower()
        model_patterns = [
            "unsupported model",
            "invalid model",
            "model not found",
        ]
        return any(pattern in message_lower for pattern in model_patterns)

    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
        model = self._extract_model_name(message, context)
        provider = context.get("provider", self._guess_provider_from_model(model))

        suggestions = self._get_model_suggestions(provider)

        fix_msg = "Update the 'model' field in your agent config"
        if suggestions:
            fix_msg += f" to one of: {', '.join(suggestions)}"

        return UserError(
            category="Model Error",
            title="Invalid model specified",
            details=f"Model '{model}' is not available for provider '{provider}'",
            fix=fix_msg,
            context={**context, "model": model, "provider": provider},
            docs_url=f"https://docs.runagac.com/models/{provider}",
        )

    def _extract_model_name(self, message: str, context: dict) -> str:
        """Extract model name from error message or context."""
        match = re.search(r"['\"]([^'\"]+)['\"].*not supported", message)
        if match:
            return match.group(1)

        return str(context.get("model", "unknown"))

    def _guess_provider_from_model(self, model: str) -> str:
        """Guess provider from model name."""
        if "claude" in model.lower():
            return "anthropic"
        if "gpt" in model.lower():
            return "openai"
        if "gemini" in model.lower():
            return "gemini"
        return "unknown"

    def _get_model_suggestions(self, provider: str) -> list:
        """Get model suggestions for a provider."""
        suggestions = {
            "anthropic": [
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ],
            "openai": ["gpt-4-turbo-preview", "gpt-4", "gpt-3.5-turbo"],
            "gemini": ["gemini-pro", "gemini-pro-vision"],
        }
        return suggestions.get(provider, [])
