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
        config_key: str = None,
        context: dict = None,
        cause: Exception = None,
    ):
        ctx = dict(context) if context else {}
        if reason is not None:
            effective_key = config_key or message
            msg = f"Configuration validation failed for '{effective_key}': {reason}"
            ctx.update({"config_key": effective_key, "reason": reason})
        elif config_key is not None:
            msg = f"Configuration validation failed for '{config_key}'"
            ctx["config_key"] = config_key
        else:
            msg = message
        super().__init__(msg, context=ctx, cause=cause)


class DuplicateFunctionError(ConfigurationError):
    """Raised when duplicate @udf_tool function names are detected."""

    def __init__(
        self,
        message: str = None,
        *,
        function_name: str = None,
        existing_location: str = None,
        existing_file: str = None,
        new_location: str = None,
        new_file: str = None,
        context: dict = None,
        cause: Exception = None,
    ):
        if function_name:
            msg = f"Duplicate UDF function name detected: '{function_name}'"
            if existing_location and new_location:
                msg += f"\n  Existing: {existing_location} (in {existing_file})"
                msg += f"\n  New:      {new_location} (in {new_file})"
            msg += (
                "\n\nSuggestions:"
                "\n  1. Rename one of the functions to be unique"
                "\n  2. Move shared UDFs to a common shared directory"
                "\n  3. Remove the duplicate if it's unintentional"
            )
            ctx = dict(context) if context else {}
            ctx.update(
                {
                    "function_name": function_name,
                    "existing_location": existing_location,
                    "existing_file": existing_file,
                    "new_location": new_location,
                    "new_file": new_file,
                }
            )
            super().__init__(msg, context=ctx, cause=cause)
        else:
            super().__init__(message, context=context, cause=cause)


class FunctionNotFoundError(ConfigurationError):
    """Raised when a UDF is not found in the registry."""

    pass


class UDFLoadError(ConfigurationError):
    """Raised when a UDF module fails to load."""

    def __init__(
        self,
        message: str = None,
        *,
        module: str = None,
        file: str = None,
        error: str = None,
        context: dict = None,
        cause: Exception = None,
    ):
        if module and error:
            msg = f"Failed to load UDF module '{module}': {error}"
            if file:
                msg += f" (file: {file})"
            ctx = dict(context) if context else {}
            ctx.update({"module": module, "file": file, "error": error})
            super().__init__(msg, context=ctx, cause=cause)
        else:
            super().__init__(message, context=context, cause=cause)


class AgentNotFoundError(ConfigurationError):
    """Raised when a specified agent cannot be found."""

    pass


class ProjectNotFoundError(ConfigurationError):
    """Raised when a command requires being in a project but agent_actions.yml is not found."""

    pass
