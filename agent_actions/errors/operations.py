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
        *,
        missing_variables: list,
        available_variables: list,
        agent_name: str,
        mode: str,
        cause: Exception,
        namespace_context: dict = None,
        template_line: int = None,
    ):
        """
        Initialize TemplateVariableError.

        Args:
            missing_variables: List of undefined variable names
            available_variables: List of available variable names
            agent_name: Name of the agent
            mode: Processing mode (batch/online)
            cause: Original Jinja2 exception
            namespace_context: Dict mapping namespace names to their available fields
            template_line: Line number in template where error occurred
        """
        self.missing_variables = missing_variables
        self.available_variables = available_variables
        self.agent_name = agent_name
        self.mode = mode
        self.namespace_context = namespace_context or {}
        self.template_line = template_line

        ctx = {
            "missing_variables": missing_variables,
            "available_variables": available_variables,
            "agent_name": agent_name,
            "mode": mode,
        }
        if namespace_context:
            ctx["namespace_context"] = namespace_context
        if template_line is not None:
            ctx["template_line"] = template_line

        msg = f"Template for '{agent_name}' references undefined variables: {', '.join(missing_variables)}"
        super().__init__(msg, context=ctx, cause=cause)
