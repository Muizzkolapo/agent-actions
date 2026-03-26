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

        # Include the exception type so the user can search/report it.
        root_type = type(root).__name__
        details = f"{root_type}: {message}" if message else root_type

        return UserError(
            category="Error",
            title=title,
            details=details,
            fix="Check your configuration and try again. "
            "Run with --verbose for the full traceback, "
            "or check logs/events.json for details.",
            context=context,
            docs_url="https://docs.runagac.com/troubleshooting",
        )
