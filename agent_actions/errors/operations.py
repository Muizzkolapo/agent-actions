"""Operational errors for agent execution and template rendering."""

from typing import Any

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
        namespace_context: dict | None = None,
        template_line: int | None = None,
        field_context_metadata: dict | None = None,
        storage_hints: dict | None = None,
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
            field_context_metadata: Metadata about stored vs loaded fields per namespace
            storage_hints: Dict mapping var names to storage info when field exists
                in storage but wasn't loaded (missing schema declaration)
        """
        self.missing_variables = missing_variables
        self.available_variables = available_variables
        self.agent_name = agent_name
        self.mode = mode
        self.namespace_context = namespace_context or {}
        self.template_line = template_line
        self.field_context_metadata = field_context_metadata or {}
        self.storage_hints = storage_hints or {}

        ctx: dict[str, Any] = {
            "missing_variables": missing_variables,
            "available_variables": available_variables,
            "agent_name": agent_name,
            "mode": mode,
        }
        if namespace_context:
            ctx["namespace_context"] = namespace_context
        if template_line is not None:
            ctx["template_line"] = template_line
        if field_context_metadata:
            ctx["field_context_metadata"] = field_context_metadata
        if storage_hints:
            ctx["storage_hints"] = storage_hints

        msg = f"Template for '{agent_name}' references undefined variables: {', '.join(missing_variables)}"
        super().__init__(msg, context=ctx, cause=cause)
