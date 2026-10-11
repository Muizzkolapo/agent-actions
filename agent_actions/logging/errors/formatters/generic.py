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
        operation = context.get("operation")
        agent = context.get("agent")

        # The CLI prefixes "Error:" itself, so the category must not start with it.
        what = operation.replace("_", " ") if operation else None
        subject = f"agent '{agent}'" if agent else None
        title = f"{what} for {subject}" if what and subject else (what or subject or "command")

        # Include the exception type so the user can search/report it.
        root_type = type(root).__name__
        details = f"{root_type}: {message}" if message else root_type

        return UserError(
            category="Operation Failed",
            title=title,
            details=details,
            fix=context.get("hint")
            or "Check your configuration and try again. "
            "Run with --verbose for the full traceback, "
            "or check logs/events.json for details.",
            context=context,
            docs_url="https://docs.runagac.com/troubleshooting",
        )
