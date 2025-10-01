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
            from agent_actions.core.safe_format import format_exception_context

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
    
    def __init__(self, config_key: str, reason: str, **kwargs):
        message = f"Configuration validation failed for '{config_key}': {reason}"
        super().__init__(message, **kwargs)


class EnvironmentConfigError(ConfigurationError):
    """Raised when environment variable configuration is invalid or missing."""
    
    def __init__(self, var_name: str, reason: str = "not set", **kwargs):
        message = f"Environment variable '{var_name}' {reason}"
        super().__init__(message, **kwargs)


# Processing-related exceptions
class ProcessingError(AgentActionsException):
    """Base exception for processing operations."""
    pass


class ValidationError(ProcessingError):
    """Raised when data validation fails."""
    pass


class SchemaValidationError(ValidationError):
    """Raised when schema validation fails."""
    
    def __init__(self, schema_type: str, validation_errors: Any, **kwargs):
        message = f"Schema validation failed for {schema_type}: {validation_errors}"
        super().__init__(message, **kwargs)


class PromptValidationError(ValidationError):
    """Raised when prompt validation fails."""
    
    def __init__(self, prompt_type: str, reason: str, **kwargs):
        message = f"Prompt validation failed for {prompt_type}: {reason}"
        super().__init__(message, **kwargs)


class DataValidationError(ValidationError):
    """Raised when data validation fails."""
    
    def __init__(self, field: str, expected: str, actual: str, **kwargs):
        message = f"Data validation failed for field '{field}': expected {expected}, got {actual}"
        super().__init__(message, **kwargs)


class TransformationError(ProcessingError):
    """Raised when data transformation fails."""
    
    def __init__(self, source_type: str, target_type: str, reason: str, **kwargs):
        message = f"Failed to transform from {source_type} to {target_type}: {reason}"
        super().__init__(message, **kwargs)


class GenerationError(ProcessingError):
    """Raised when data generation fails."""
    pass


class WorkflowError(ProcessingError):
    """Raised when an error occurs in workflow processing."""
    
    def __init__(self, workflow_stage: str, reason: str, **kwargs):
        message = f"Workflow error at stage '{workflow_stage}': {reason}"
        super().__init__(message, **kwargs)


# External service exceptions
class ExternalServiceError(AgentActionsException):
    """Base exception for external service interactions."""
    
    def __init__(self, service_name: str, reason: str, **kwargs):
        message = f"External service '{service_name}' error: {reason}"
        super().__init__(message, **kwargs)


class VendorAPIError(ExternalServiceError):
    """Raised when an error occurs during a call to a vendor's API."""
    
    def __init__(self, vendor: str, endpoint: str, status_code: Optional[int] = None, **kwargs):
        reason = f"API call to {endpoint} failed"
        if status_code:
            reason += f" with status code {status_code}"
        super().__init__(vendor, reason, **kwargs)


class OpenAIError(VendorAPIError):
    """Specific error for OpenAI API failures."""
    
    def __init__(self, endpoint: str, **kwargs):
        super().__init__("OpenAI", endpoint, **kwargs)


class AnthropicError(VendorAPIError):
    """Specific error for Anthropic API failures."""
    
    def __init__(self, endpoint: str, **kwargs):
        super().__init__("Anthropic", endpoint, **kwargs)


class GeminiError(VendorAPIError):
    """Specific error for Google Gemini API failures."""
    
    def __init__(self, endpoint: str, **kwargs):
        super().__init__("Gemini", endpoint, **kwargs)


class NetworkError(ExternalServiceError):
    """Raised when network-related errors occur."""
    
    def __init__(self, operation: str, reason: str, **kwargs):
        super().__init__("Network", f"{operation} failed: {reason}", **kwargs)


class RateLimitError(ExternalServiceError):
    """Raised when API rate limits are exceeded."""
    
    def __init__(self, service: str, retry_after: Optional[int] = None, **kwargs):
        reason = "Rate limit exceeded"
        if retry_after:
            reason += f", retry after {retry_after} seconds"
        super().__init__(service, reason, **kwargs)


# Resource-related exceptions
class ResourceError(AgentActionsException):
    """Base exception for resource-related errors."""
    pass


class FileSystemError(ResourceError):
    """Base exception for file system operations."""
    pass


class FileLoadError(FileSystemError):
    """Raised when a file cannot be loaded."""
    
    def __init__(self, file_path: str, reason: str = "not found", **kwargs):
        message = f"Failed to load file '{file_path}': {reason}"
        super().__init__(message, **kwargs)


class FileWriteError(FileSystemError):
    """Raised when a file cannot be written."""
    
    def __init__(self, file_path: str, reason: str, **kwargs):
        message = f"Failed to write file '{file_path}': {reason}"
        super().__init__(message, **kwargs)


class DirectoryError(FileSystemError):
    """Raised when directory operations fail."""
    
    def __init__(self, directory_path: str, operation: str, reason: str, **kwargs):
        message = f"Directory operation '{operation}' failed for '{directory_path}': {reason}"
        super().__init__(message, **kwargs)


class MemoryError(ResourceError):
    """Raised when memory-related issues occur."""
    
    def __init__(self, operation: str, required: Optional[str] = None, **kwargs):
        message = f"Memory error during {operation}"
        if required:
            message += f", required: {required}"
        super().__init__(message, **kwargs)


class DependencyError(ResourceError):
    """
    Raised when a required dependency is not provided.
    
    This exception should be raised when a class requires dependencies
    to be injected but they are not provided during instantiation.
    """
    
    def __init__(self, class_name: str, missing_dependency: str, **kwargs):
        message = (
            f"{class_name} requires {missing_dependency} to be provided. "
            f"Please ensure all dependencies are properly injected."
        )
        super().__init__(message, **kwargs)
        self.class_name = class_name
        self.missing_dependency = missing_dependency


# Operational exceptions
class OperationalError(AgentActionsException):
    """Base exception for operational errors."""
    pass


class AgentExecutionError(OperationalError):
    """Raised when an error occurs during agent execution."""
    
    def __init__(self, agent_name: str, stage: str, reason: str, **kwargs):
        message = f"Agent '{agent_name}' execution failed at {stage}: {reason}"
        super().__init__(message, **kwargs)


class TemplateRenderingError(OperationalError):
    """Raised when an error occurs during template rendering."""

    def __init__(self, template_name: str, reason: str = None, **kwargs):
        # Backward compatibility: if reason is None, template_name is the full message
        if reason is None:
            message = template_name  # Old usage: TemplateRenderingError("message")
        else:
            message = f"Failed to render template '{template_name}': {reason}"
        super().__init__(message, **kwargs)


class SerializationError(OperationalError):
    """Raised when data serialization/deserialization fails."""

    def __init__(self, operation: str, data_type: str, reason: str, **kwargs):
        message = f"Serialization {operation} failed for {data_type}: {reason}"
        super().__init__(message, **kwargs)


class AgentNotFoundError(ConfigurationError):
    """Raised when a specified agent cannot be found."""

    def __init__(self, agent_name: str, reason: str = "not found", **kwargs):
        message = f"Agent '{agent_name}' {reason}"
        super().__init__(message, **kwargs)
        self.agent_name = agent_name


# Backward compatibility aliases
# These maintain compatibility with existing code
ProcessorError = ProcessingError
LoaderError = FileSystemError
DataParseError = ValidationError
UnsupportedFormatError = ValidationError
# NOTE: FileNotFoundError, PermissionError, and MemoryError aliases removed
# to avoid shadowing Python built-ins. Use FileLoadError, FileSystemError,
# and ResourceError directly, or import from builtins if needed.