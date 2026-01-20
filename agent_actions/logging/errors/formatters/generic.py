"""Generic/fallback error formatter."""

from typing import Dict, Any
from .error_formatter_base import ErrorFormatter
from ..user_error import UserError


class GenericErrorFormatter(ErrorFormatter):
    """Handles unknown/generic errors (fallback formatter)."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        """Always returns True - this is the fallback formatter."""
        return True

    def format(
        self, exc: Exception, root: Exception, message: str, context: Dict[str, Any]
    ) -> UserError:
        """Handle unknown/generic errors."""
        operation = context.get("operation", "operation")
        agent = context.get("agent")

        title = f"Error during {operation.replace('_', ' ')}"
        if agent:
            title += f" for agent '{agent}'"

        return UserError(
            category="Error",
            title=title,
            details=message,
            fix="Check your configuration and try again",
            context=context,
            docs_url="https://docs.agent-actions.com/troubleshooting",
        )
