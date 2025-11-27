"""
Centralized exception hierarchy for Agent Actions.

This module provides a comprehensive exception hierarchy that standardizes
error handling across the entire application. It consolidates and extends
existing exception classes from various modules.

Exception Hierarchy:
    AgentActionsException (base)
    ├── ConfigurationError
    │   ├── ConfigValidationError
    │   └── EnvironmentConfigError
    ├── ProcessingError
    │   ├── ValidationError
    │   │   ├── SchemaValidationError
    │   │   ├── PromptValidationError
    │   │   └── DataValidationError
    │   ├── TransformationError
    │   ├── GenerationError
    │   └── WorkflowError
    ├── ExternalServiceError
    │   ├── VendorAPIError
    │   │   ├── OpenAIError
    │   │   ├── AnthropicError
    │   │   └── GeminiError
    │   ├── NetworkError
    │   └── RateLimitError
    ├── ResourceError
    │   ├── FileSystemError
    │   │   ├── FileLoadError
    │   │   ├── FileWriteError
    │   │   └── DirectoryError
    │   ├── MemoryError
    │   └── DependencyError
    └── OperationalError
        ├── AgentExecutionError
        ├── TemplateRenderingError
        └── SerializationError

Usage Guide:
-----------

All exceptions follow a standard three-parameter pattern for consistency and
proper error context preservation:

    raise SomeException(
        "Clear human-readable error message",
        context={'key1': 'value1', 'key2': 'value2'},
        cause=original_exception  # keyword-only, only when wrapping
    )

✅ DO THIS - Standard Pattern Examples:
---------------------------------------

1. Configuration Error (no cause):
    raise ConfigValidationError(
        config_key="model_vendor",
        reason="Must be one of: openai, anthropic, gemini",
        context={'provided_value': config.get('model_vendor')}
    )

2. File Error (with cause):
    try:
        with open(file_path) as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise FileLoadError(
            file_path=file_path,
            operation="read",
            context={'file_type': 'json'},
            cause=e
        )

3. Processing Error (with cause):
    try:
        result = vendor.process(data)
    except Exception as e:
        raise ProcessingError(
            "Failed to process vendor API response",
            context={'vendor': vendor_name, 'operation': 'process_response'},
            cause=e
        )

4. Validation Error (merging context):
    def validate_config(config, agent_name):
        if 'model_vendor' not in config:
            raise ConfigValidationError(
                config_key="model_vendor",
                reason="Required configuration key is missing",
                context={'agent_name': agent_name, 'available_keys': list(config.keys())}
            )

❌ DON'T DO THIS - Anti-Patterns:
---------------------------------

1. ❌ String interpolation in context:
    # WRONG - context is a string
    raise AgentActionsException(
        "Error occurred",
        f"File: {file_path}, Operation: {operation}"  # ❌ NOT a dict
    )

    # CORRECT - context is a dict
    raise AgentActionsException(
        "Error occurred",
        context={'file_path': file_path, 'operation': operation}  # ✅ dict
    )

2. ❌ Missing cause parameter when wrapping:
    # WRONG - loses exception chain
    try:
        process_file()
    except IOError:
        raise AgentActionsException("Processing failed")  # ❌ Lost context

    # CORRECT - preserves exception chain
    try:
        process_file()
    except IOError as e:
        raise AgentActionsException(
            "Processing failed",
            context={'file_path': file_path},
            cause=e  # ✅ Preserved
        )

3. ❌ Not using keyword-only cause:
    # WRONG - positional cause parameter
    raise AgentActionsException("Error", context, e)  # ❌ Positional

    # CORRECT - keyword-only cause parameter
    raise AgentActionsException("Error", context, cause=e)  # ✅ Keyword-only

4. ❌ Using generic exceptions instead of domain-specific:
    # WRONG - generic exception
    raise ValueError("Invalid model vendor")  # ❌ Generic

    # CORRECT - domain-specific exception
    raise ConfigValidationError(
        config_key="model_vendor",
        reason="Invalid model vendor",
        context={'provided_value': vendor}
    )  # ✅ Domain-specific

Key Principles:
--------------

1. **Always use dict for context**: Never pass strings, always pass dicts with
   relevant key-value pairs that help debug the issue.

2. **Always chain exceptions**: When catching and re-raising, use the cause
   parameter to maintain the full exception chain for debugging.

3. **Use domain-specific exceptions**: Choose the most specific exception class
   that matches your error scenario (e.g., ConfigValidationError instead of
   ValueError).

4. **Include operation context**: Always include 'operation' key in context to
   identify where in the code the error occurred.

5. **Preserve debugging info**: Include file paths, config keys, agent names,
   and other relevant data that helps locate and fix the issue.
"""

from typing import Any, Dict, Optional


class AgentActionsException(Exception):
    """
    Base exception class for all Agent Actions errors.
    
    This is the root of our exception hierarchy. All custom exceptions
    should inherit from this class to ensure consistent error handling.
    """
    
    def __init__(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        """
        Initialize the exception with optional context and cause.

        Args:
            message: The error message
            context: Optional dictionary containing contextual information
            cause: Optional original exception that caused this error
        """
        super().__init__(message)
        self.context = context or {}
        self.cause = cause

        # Set __cause__ to maintain proper exception chain for get_error_chain
        # This allows both exc.cause and exc.__cause__ to work
        if cause is not None:
            self.__cause__ = cause
        
    def __str__(self) -> str:
        """Return a string representation including context if available."""
        try:
            from agent_actions.utilities.safe_format import format_exception_context

            # Safely get base message
            try:
                base_msg = super().__str__()
            except Exception:
                # Fallback to message attribute or class name
                base_msg = getattr(self, 'message', f"{type(self).__name__}")

            if self.context:
                # Use safe context formatting
                context_str = format_exception_context(self.context)
                if context_str:
                    return f"{base_msg} [Context: {context_str}]"

            return base_msg

        except Exception:
            # Ultimate fallback - should never fail
            try:
                return getattr(self, 'message', f"{type(self).__name__}: formatting failed")
            except Exception:
                return "Exception occurred (formatting completely failed)"


# Configuration-related exceptions
class ConfigurationError(AgentActionsException):
    """Raised when there is an error in configuration files or settings."""
    pass


class ConfigValidationError(ConfigurationError):
    """Raised when configuration validation fails."""

    def __init__(
        self,
        config_key: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize ConfigValidationError.

        Args:
            config_key: The configuration key that failed validation
            reason: Why the validation failed
            context: Additional context dict (merged with config_key/reason)
            cause: The underlying exception that caused this error
        """
        message = f"Configuration validation failed for '{config_key}': {reason}"
        # Build context from params
        ctx = context or {}
        ctx.update({'config_key': config_key, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


class DuplicateFunctionError(ConfigurationError):
    """Raised when duplicate @udf_tool function names detected."""

    def __init__(
        self,
        function_name: str,
        existing_location: str,
        existing_file: str,
        new_location: str,
        new_file: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize DuplicateFunctionError.

        Args:
            function_name: The duplicate function name
            existing_location: Module path of existing function
            existing_file: File path of existing function
            new_location: Module path of new duplicate function
            new_file: File path of new duplicate function
            context: Additional context dict
            cause: The underlying exception that caused this error
        """
        message = f"Duplicate function name: '{function_name}'"
        ctx = context or {}
        ctx.update({
            'function_name': function_name,
            'existing_location': existing_location,
            'existing_file': existing_file,
            'new_location': new_location,
            'new_file': new_file
        })
        super().__init__(message, context=ctx, cause=cause)


class FunctionNotFoundError(ConfigurationError):
    """Raised when UDF not found in registry."""

    def __init__(
        self,
        function_name: str,
        available_functions: list,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize FunctionNotFoundError.

        Args:
            function_name: Name of the function that was not found
            available_functions: List of available function names
            context: Additional context dict
            cause: The underlying exception that caused this error
        """
        message = f"Function '{function_name}' not found"
        ctx = context or {}
        ctx.update({
            'function_name': function_name,
            'available_functions': available_functions
        })
        super().__init__(message, context=ctx, cause=cause)


class UDFLoadError(ConfigurationError):
    """Raised when UDF module fails to load."""

    def __init__(
        self,
        module: str,
        file: str,
        error: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize UDFLoadError.

        Args:
            module: Module name that failed to load
            file: File path of the module
            error: Error message from the failed import
            context: Additional context dict
            cause: The underlying exception that caused this error
        """
        message = f"Error loading UDF module '{module}'"
        ctx = context or {}
        ctx.update({
            'module': module,
            'file': file,
            'error': error
        })
        super().__init__(message, context=ctx, cause=cause)


# Processing-related exceptions
class ProcessingError(AgentActionsException):
    """Base exception for processing operations."""
    pass


class ValidationError(ProcessingError):
    """Raised when data validation fails."""
    pass


class PromptValidationError(ValidationError):
    """Raised when prompt validation fails."""

    def __init__(
        self,
        prompt_type: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize PromptValidationError.

        Args:
            prompt_type: Type of prompt that failed validation
            reason: Why validation failed
            context: Additional context dict (merged with prompt_type/reason)
            cause: The underlying exception that caused this error
        """
        message = f"Prompt validation failed for {prompt_type}: {reason}"
        ctx = context or {}
        ctx.update({'prompt_type': prompt_type, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


class DataValidationError(ValidationError):
    """Raised when data validation fails."""

    def __init__(
        self,
        field: str,
        expected: str,
        actual: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize DataValidationError.

        Args:
            field: Field name that failed validation
            expected: Expected value/type
            actual: Actual value/type received
            context: Additional context dict (merged with field/expected/actual)
            cause: The underlying exception that caused this error
        """
        message = f"Data validation failed for field '{field}': expected {expected}, got {actual}"
        ctx = context or {}
        ctx.update({'field': field, 'expected': expected, 'actual': actual})
        super().__init__(message, context=ctx, cause=cause)


class TransformationError(ProcessingError):
    """Raised when data transformation fails."""

    def __init__(
        self,
        source_type: str,
        target_type: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize TransformationError.

        Args:
            source_type: Type being transformed from
            target_type: Type being transformed to
            reason: Why transformation failed
            context: Additional context dict (merged with source/target/reason)
            cause: The underlying exception that caused this error
        """
        message = f"Failed to transform from {source_type} to {target_type}: {reason}"
        ctx = context or {}
        ctx.update({'source_type': source_type, 'target_type': target_type, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


class GenerationError(ProcessingError):
    """Raised when data generation fails."""
    pass


class WorkflowError(ProcessingError):
    """Raised when an error occurs in workflow processing."""

    def __init__(
        self,
        workflow_stage: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize WorkflowError.

        Args:
            workflow_stage: Stage where the workflow failed
            reason: Why the workflow failed
            context: Additional context dict (merged with workflow_stage/reason)
            cause: The underlying exception that caused this error
        """
        message = f"Workflow error at stage '{workflow_stage}': {reason}"
        ctx = context or {}
        ctx.update({'workflow_stage': workflow_stage, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


# External service exceptions
class ExternalServiceError(AgentActionsException):
    """Base exception for external service interactions."""

    def __init__(
        self,
        service_name: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize ExternalServiceError.

        Args:
            service_name: Name of the external service
            reason: Reason for the service error
            context: Additional context dict (merged with service_name/reason)
            cause: The underlying exception that caused this error
        """
        message = f"External service '{service_name}' error: {reason}"
        ctx = context or {}
        ctx.update({'service_name': service_name, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


class VendorAPIError(ExternalServiceError):
    """Raised when an error occurs during a call to a vendor's API."""

    def __init__(
        self,
        vendor: str,
        endpoint: str,
        status_code: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize VendorAPIError.

        Args:
            vendor: Name of the vendor/service
            endpoint: API endpoint that was called
            status_code: HTTP status code if applicable
            context: Additional context dict (merged with vendor/endpoint/status_code)
            cause: The underlying exception that caused this error
        """
        reason = f"API call to {endpoint} failed"
        if status_code:
            reason += f" with status code {status_code}"
        ctx = context or {}
        ctx.update({'vendor': vendor, 'endpoint': endpoint, 'status_code': status_code})
        super().__init__(vendor, reason, context=ctx, cause=cause)


class AnthropicError(VendorAPIError):
    """Specific error for Anthropic API failures."""

    def __init__(
        self,
        endpoint: str,
        status_code: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize AnthropicError.

        Args:
            endpoint: API endpoint that was called
            status_code: HTTP status code if applicable
            context: Additional context dict (merged with vendor/endpoint/status_code)
            cause: The underlying exception that caused this error
        """
        super().__init__("Anthropic", endpoint, status_code=status_code, context=context, cause=cause)


class NetworkError(ExternalServiceError):
    """Raised when network-related errors occur (timeout, connection, etc).

    This exception is used for network issues like connection timeouts,
    DNS resolution failures, or other network-level problems.
    """

    def __init__(
        self,
        operation: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """Initialize NetworkError with helpful suggestion.

        Args:
            operation: The network operation that failed (e.g., 'API request', 'file download')
            reason: Why the operation failed (e.g., 'connection timeout', 'DNS resolution failed')
            context: Additional context dict (merged with operation/reason)
            cause: The underlying exception that caused this error
            suggestion: Helpful fix suggestion for the user
        """
        ctx = context or {}
        ctx.update({'operation': operation, 'reason': reason})
        if suggestion:
            ctx['suggestion'] = suggestion
        else:
            # Provide default suggestion based on common network issues
            ctx['suggestion'] = 'Check your internet connection and try again. If the problem persists, check firewall settings or VPN configuration.'
        super().__init__('network', reason, context=ctx, cause=cause)


class RateLimitError(VendorAPIError):
    """Raised when API rate limits are exceeded.

    This exception indicates that the API request was rejected due to
    rate limiting. The caller should implement exponential backoff retry logic.
    """

    def __init__(
        self,
        vendor: str,
        endpoint: str = 'unknown',
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None,
        retry_after: Optional[int] = None
    ) -> None:
        """Initialize RateLimitError with retry guidance.

        Args:
            vendor: Name of the vendor/service (e.g., 'OpenAI', 'Anthropic')
            endpoint: API endpoint that was rate-limited
            context: Additional context dict
            cause: The underlying exception that caused this error
            retry_after: Number of seconds to wait before retrying (if provided by API)
        """
        ctx = context or {}
        if retry_after:
            ctx['retry_after_seconds'] = retry_after
            ctx['suggestion'] = f"Wait {retry_after} seconds before retrying, or upgrade your API plan for higher rate limits."
        else:
            ctx['suggestion'] = "Wait a few minutes before retrying, or upgrade your API plan for higher rate limits. Consider implementing exponential backoff."

        # Set status code to 429 (standard HTTP rate limit status)
        super().__init__(vendor, endpoint, status_code=429, context=ctx, cause=cause)


# Resource-related exceptions
class ResourceError(AgentActionsException):
    """Base exception for resource-related errors."""
    pass


class FileSystemError(ResourceError):
    """Base exception for file system operations."""
    pass


class FileLoadError(FileSystemError):
    """Raised when a file cannot be loaded."""

    def __init__(
        self,
        file_path: str,
        reason: str = "not found",
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize FileLoadError.

        Args:
            file_path: Path to the file that failed to load
            reason: Reason for the load failure
            context: Additional context dict (merged with file_path/reason)
            cause: The underlying exception that caused this error
        """
        message = f"Failed to load file '{file_path}': {reason}"
        ctx = context or {}
        ctx.update({'file_path': file_path, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


class FileWriteError(FileSystemError):
    """Raised when a file cannot be written."""

    def __init__(
        self,
        file_path: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize FileWriteError.

        Args:
            file_path: Path to the file that failed to write
            reason: Reason for the write failure
            context: Additional context dict (merged with file_path/reason)
            cause: The underlying exception that caused this error
        """
        message = f"Failed to write file '{file_path}': {reason}"
        ctx = context or {}
        ctx.update({'file_path': file_path, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


class DirectoryError(FileSystemError):
    """Raised when directory operations fail."""

    def __init__(
        self,
        directory_path: str,
        operation: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize DirectoryError.

        Args:
            directory_path: Path to the directory
            operation: Directory operation that failed
            reason: Reason for the operation failure
            context: Additional context dict (merged with directory_path/operation/reason)
            cause: The underlying exception that caused this error
        """
        message = f"Directory operation '{operation}' failed for '{directory_path}': {reason}"
        ctx = context or {}
        ctx.update({'directory_path': directory_path, 'operation': operation, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


class MemoryError(ResourceError):
    """Raised when memory-related issues occur."""

    def __init__(
        self,
        operation: str,
        required: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize MemoryError.

        Args:
            operation: Operation that encountered memory issues
            required: Required memory amount/specification
            context: Additional context dict (merged with operation/required)
            cause: The underlying exception that caused this error
        """
        message = f"Memory error during {operation}"
        if required:
            message += f", required: {required}"
        ctx = context or {}
        ctx.update({'operation': operation, 'required': required})
        super().__init__(message, context=ctx, cause=cause)


class DependencyError(ResourceError):
    """
    Raised when a required dependency is not provided.

    This exception should be raised when a class requires dependencies
    to be injected but they are not provided during instantiation.
    """

    def __init__(
        self,
        class_name: str,
        missing_dependency: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize DependencyError.

        Args:
            class_name: Name of the class missing the dependency
            missing_dependency: Name/description of the missing dependency
            context: Additional context dict (merged with class_name/missing_dependency)
            cause: The underlying exception that caused this error
        """
        message = (
            f"{class_name} requires {missing_dependency} to be provided. "
            f"Please ensure all dependencies are properly injected."
        )
        ctx = context or {}
        ctx.update({'class_name': class_name, 'missing_dependency': missing_dependency})
        super().__init__(message, context=ctx, cause=cause)
        self.class_name = class_name
        self.missing_dependency = missing_dependency


# Operational exceptions
class OperationalError(AgentActionsException):
    """Base exception for operational errors."""
    pass


class AgentExecutionError(OperationalError):
    """Raised when an error occurs during agent execution."""

    def __init__(
        self,
        agent_name: str,
        stage: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize AgentExecutionError.

        Args:
            agent_name: Name of the agent that failed
            stage: Stage/phase of execution where the failure occurred
            reason: Reason for the execution failure
            context: Additional context dict (merged with agent_name/stage/reason)
            cause: The underlying exception that caused this error
        """
        message = f"Agent '{agent_name}' execution failed at {stage}: {reason}"
        ctx = context or {}
        ctx.update({'agent_name': agent_name, 'stage': stage, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


class TemplateRenderingError(OperationalError):
    """Raised when an error occurs during template rendering."""

    def __init__(
        self,
        template_name: str,
        reason: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize TemplateRenderingError.

        Args:
            template_name: Name of the template that failed to render
            reason: Reason for the rendering failure (if None, template_name is used as full message for backward compatibility)
            context: Additional context dict (merged with template_name/reason)
            cause: The underlying exception that caused this error
        """
        # Backward compatibility: if reason is None, template_name is the full message
        if reason is None:
            message = template_name  # Old usage: TemplateRenderingError("message")
            ctx = context or {}
        else:
            message = f"Failed to render template '{template_name}': {reason}"
            ctx = context or {}
            ctx.update({'template_name': template_name, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)


class AgentNotFoundError(ConfigurationError):
    """Raised when a specified agent cannot be found."""

    def __init__(
        self,
        agent_name: str,
        reason: str = "not found",
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize AgentNotFoundError.

        Args:
            agent_name: Name of the agent that was not found
            reason: Reason why the agent was not found
            context: Additional context dict (merged with agent_name/reason)
            cause: The underlying exception that caused this error
        """
        message = f"Agent '{agent_name}' {reason}"
        ctx = context or {}
        ctx.update({'agent_name': agent_name, 'reason': reason})
        super().__init__(message, context=ctx, cause=cause)
        self.agent_name = agent_name


class ProjectNotFoundError(ConfigurationError):
    """Raised when a command requires being in a project but agent_actions.yml not found."""

    def __init__(
        self,
        marker_file: str = "agent_actions.yml",
        search_path: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        *,
        cause: Optional[Exception] = None
    ) -> None:
        """Initialize ProjectNotFoundError.

        Args:
            marker_file: Name of the marker file being searched for
            search_path: Path where search started
            context: Additional context dict (merged with marker_file/search_path)
            cause: The underlying exception that caused this error
        """
        import os
        message = f"Not in an agent-actions project"
        ctx = context or {}
        ctx.update({
            'marker_file': marker_file,
            'search_path': search_path or os.getcwd(),
            'solution_1': 'Navigate to your agent-actions project directory',
            'solution_2': "Run 'agent-actions init' to create a new project"
        })
        super().__init__(message, context=ctx, cause=cause)


# Backward compatibility aliases
# These maintain compatibility with existing code
ProcessorError = ProcessingError
LoaderError = FileSystemError
DataParseError = ValidationError
UnsupportedFormatError = ValidationError
# NOTE: FileNotFoundError, PermissionError, and MemoryError aliases removed
# to avoid shadowing Python built-ins. Use FileLoadError, FileSystemError,
# and ResourceError directly, or import from builtins if needed.