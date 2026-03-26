"""Authentication error formatter."""

from typing import Any

from ..user_error import UserError
from .base import ErrorFormatter


class AuthenticationErrorFormatter(ErrorFormatter):
    """Handles authentication errors."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        exc_names = [type(exc).__name__, type(root).__name__]

        if any("Auth" in name for name in exc_names):
            return True

        message_lower = message.lower()
        auth_patterns = [
            "api key",
            "authentication",
            "unauthorized",
            "invalid key",
            "permission denied",
            "401",
            "403",
        ]
        return any(pattern in message_lower for pattern in auth_patterns)

    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
        provider = self._extract_provider_name(message, context)

        if provider == "anthropic":
            env_var = "ANTHROPIC_API_KEY"
            console_url = "https://console.anthropic.com"
        elif provider == "openai":
            env_var = "OPENAI_API_KEY"
            console_url = "https://platform.openai.com"
        else:
            env_var = "API_KEY"
            console_url = "your provider's console"

        fix_msg = f"1. Get your API key from {console_url}\n"
        fix_msg += f"     2. Set environment variable: export {env_var}=your-key\n"
        fix_msg += f"     3. Or add to .env file: {env_var}=your-key"

        return UserError(
            category="Authentication Error",
            title=f"Invalid {provider.title()} API key",
            details="Your API key is invalid, expired, or not set",
            fix=fix_msg,
            context=context,
            docs_url="https://docs.runagac.com/setup/authentication",
        )
