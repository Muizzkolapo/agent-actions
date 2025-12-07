"""Operational errors for agent execution and template rendering."""

from agent_actions.errors.base import AgentActionsError


class OperationalError(AgentActionsError):
    """Base exception for operational errors."""
    pass


class AgentExecutionError(OperationalError):
    """Raised when an error occurs during agent execution."""
    pass


class TemplateRenderingError(OperationalError):
    """Raised when an error occurs during template rendering."""
    pass
