"""Base exception classes for agent-actions."""

from typing import Any


class AgentActionsError(Exception):
    """Base exception for all agent-actions errors."""

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        *,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.context = dict(context) if isinstance(context, dict) else (context or {})
        self.cause = cause
        if cause is not None:
            self.__cause__ = cause

    def detailed_str(self) -> str:
        """Return message with full context dict — use at debug/event boundaries."""
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
