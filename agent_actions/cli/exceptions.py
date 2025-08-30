"""
Custom exceptions for the Agent Actions CLI.

This module defines custom exception classes used throughout
the CLI application to provide more specific error handling.
"""

class AgentActionsError(Exception):
    """Base exception class for all Agent Actions errors."""
    pass


class ConfigurationError(AgentActionsError):
    """Raised when there is an error in configuration files or settings."""
    pass


class ValidationError(AgentActionsError):
    """Raised when validation of inputs, configs, or other elements fails."""
    pass


class FileNotFoundError(AgentActionsError):
    """Raised when a required file cannot be found."""
    pass


class DirectoryNotFoundError(AgentActionsError):
    """Raised when a required directory cannot be found."""
    pass


class AgentExecutionError(AgentActionsError):
    """Raised when an error occurs during agent execution."""
    pass


class SchemaValidationError(ValidationError):
    """Raised when schema validation fails."""
    pass


class PromptValidationError(ValidationError):
    """Raised when prompt validation fails."""
    pass


class ConfigValidationError(ValidationError):
    """Raised when configuration validation fails."""
    pass


class AgentNotFoundError(AgentActionsError):
    """Raised when a specified agent cannot be found."""
    pass


class WorkflowError(AgentActionsError):
    """Raised when an error occurs in the workflow processing."""
    pass


class PermissionError(AgentActionsError):
    """Raised when permission is denied for a file or directory operation."""
    pass


class TemplateRenderingError(AgentActionsError):
    """Raised when an error occurs during template rendering."""
    pass


class VendorAPIError(AgentActionsError):
    """Raised when an error occurs during a call to a vendor's API."""
    pass


class DependencyError(AgentActionsError):
    """
    Raised when a required dependency is not provided.
    
    This exception should be raised when a class requires dependencies
    to be injected but they are not provided during instantiation.
    """
    def __init__(self, class_name: str, missing_dependency: str):
        """
        Initialize the DependencyError.
        
        Args:
            class_name: Name of the class missing the dependency
            missing_dependency: Name of the missing dependency
        """
        self.class_name = class_name
        self.missing_dependency = missing_dependency
        message = f"{class_name} requires {missing_dependency} to be provided. Please ensure all dependencies are properly injected."
        super().__init__(message)