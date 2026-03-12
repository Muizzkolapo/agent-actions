"""Generic/fallback error formatter."""

from typing import Any

from ..user_error import UserError
from .base import ErrorFormatter


class GenericErrorFormatter(ErrorFormatter):
    """Handles unknown/generic errors (fallback formatter)."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        return True

    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
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
