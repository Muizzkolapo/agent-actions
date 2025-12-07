"""Configuration-related errors."""

from agent_actions.errors.base import AgentActionsError


class ConfigurationError(AgentActionsError):
    """Base exception for configuration-related errors."""
    pass


class ConfigValidationError(ConfigurationError):
    """Raised when configuration validation fails."""

    def __init__(
        self,
        message: str = None,
        reason: str = None,
        *,
        context: dict = None,
        config_key: str = None,
        cause: Exception = None
    ):
        """Initialize ConfigValidationError.

        Supports both old and new signatures:
        - New: ConfigValidationError("message", context={...}, cause=...)
        - Old keyword: ConfigValidationError(config_key="key", reason="reason", context={...})
        - Old positional: ConfigValidationError("key", "reason", context={...})

        Args:
            message: Either the full error message (new style) or config_key (old positional style)
            context: Additional context dict
            config_key: Config key that failed (old keyword style)
            reason: Reason for validation failure (old style only)
            cause: The underlying exception
        """
        # Handle old keyword style: config_key= and reason=
        if config_key is not None and reason is not None:
            msg = f"Configuration validation failed for '{config_key}': {reason}"
            ctx = context or {}
            ctx.update({'config_key': config_key, 'reason': reason})
            super().__init__(msg, context=ctx, cause=cause)
        # Handle old positional style: ConfigValidationError("key", "reason", ...)
        elif reason is not None:
            msg = f"Configuration validation failed for '{message}': {reason}"
            ctx = context or {}
            ctx.update({'config_key': message, 'reason': reason})
            super().__init__(msg, context=ctx, cause=cause)
        # New style: just message
        else:
            super().__init__(message, context=context, cause=cause)


class DuplicateFunctionError(ConfigurationError):
    """Raised when duplicate @udf_tool function names are detected."""
    pass


class FunctionNotFoundError(ConfigurationError):
    """Raised when a UDF is not found in the registry."""
    pass


class UDFLoadError(ConfigurationError):
    """Raised when a UDF module fails to load."""
    pass


class AgentNotFoundError(ConfigurationError):
    """Raised when a specified agent cannot be found."""
    pass


class ProjectNotFoundError(ConfigurationError):
    """Raised when a command requires being in a project but agent_actions.yml is not found."""
    pass


class EnvironmentConfigError(ConfigurationError):
    """Raised when environment configuration is invalid or missing."""
    pass
