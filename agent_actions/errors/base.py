"""Base exception classes for agent-actions.

This module provides the root exception class for all agent-actions errors.
We keep the hierarchy simple and clean.
"""
# Import-outside-toplevel: Avoid circular imports with utilities module
# Broad-exception-caught: Safety fallback for exception formatting

from typing import Any, Dict, Optional


class AgentActionsError(Exception):
    """Base exception for all agent-actions errors.

    This is the root of our exception hierarchy. All custom exceptions
    should inherit from this class.

    Args:
        message: The error message
        context: Optional dictionary containing contextual information for debugging
        cause: Optional original exception that caused this error

    Example:
        raise AgentActionsError(
            "Failed to process configuration",
            context={'file': 'config.yml', 'agent': 'my_agent'},
            cause=original_exception
        )
    """

    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.context = context or {}
        self.cause = cause

        # Set __cause__ to maintain proper exception chain
        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        """Return concise error message without context dump."""
        return super().__str__()

    def detailed_str(self) -> str:
        """Return message with full context — use for debug logging."""
        try:
            from agent_actions.utils.safe_format import format_exception_context

            base_msg = super().__str__()

            if self.context:
                context_str = format_exception_context(self.context)
                if context_str:
                    return f"{base_msg} [Context: {context_str}]"

            return base_msg

        except Exception:
            return super().__str__()


def get_error_detail(error: Exception) -> str:
    """Return detailed_str() for AgentActionsError, else str()."""
    if isinstance(error, AgentActionsError):
        return error.detailed_str()
    return str(error)
