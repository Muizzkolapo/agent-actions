"""Operational errors for agent execution and template rendering."""
# Unnecessary-pass: Simple exception classes inherit all behavior from parent

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


class TemplateVariableError(TemplateRenderingError):
    """Raised when Jinja2 template references undefined variables."""

    def __init__(
        self,
        missing_variables: list,
        available_variables: list,
        agent_name: str,
        mode: str,
        cause: Exception,
    ):
        """
        Initialize TemplateVariableError.

        Args:
            missing_variables: List of undefined variable names
            available_variables: List of available variable names
            agent_name: Name of the agent
            mode: Processing mode (batch/online)
            cause: Original Jinja2 exception
        """
        self.missing_variables = missing_variables
        self.available_variables = available_variables
        self.agent_name = agent_name
        self.mode = mode
        self.cause = cause

        msg = f"Template for '{agent_name}' references undefined variables: {', '.join(missing_variables)}"
        super().__init__(msg)
