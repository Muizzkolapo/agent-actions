"""DEPRECATED: Backward compatibility shim for old exception imports.

⚠️  This module is deprecated. New code should import from agent_actions.errors instead.

Old pattern (deprecated):
    from agent_actions.shared.exceptions import ValidationError, ConfigurationError

New pattern (recommended):
    from agent_actions.errors import ValidationError, ConfigurationError

This module re-exports all errors from the new modular error hierarchy
to maintain backward compatibility with existing code.

The new error hierarchy is organized by domain:
- agent_actions.errors.base - Base error class
- agent_actions.errors.configuration - Config errors
- agent_actions.errors.validation - Validation errors
- agent_actions.errors.processing - Processing/workflow errors
- agent_actions.errors.external_services - Vendor API errors
- agent_actions.errors.filesystem - File operation errors
- agent_actions.errors.resources - Resource errors
- agent_actions.errors.operations - Operational errors

All errors now use a simpler signature:
    raise ValidationError(
        "Error message",
        context={'key': 'value'},
        cause=original_exception
    )
"""

# Import everything from the new errors module for backward compatibility
from agent_actions.errors import (
    # Base
    AgentActionsError,
    # Common
    InvalidParameterError,
    # Configuration
    ConfigurationError,
    ConfigValidationError,
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError,
    AgentNotFoundError,
    ProjectNotFoundError,
    EnvironmentConfigError,
    # Validation
    ValidationError,
    PromptValidationError,
    DataValidationError,
    SchemaValidationError,
    # Processing
    ProcessingError,
    TransformationError,
    GenerationError,
    WorkflowError,
    SerializationError,
    # External Services
    ExternalServiceError,
    VendorAPIError,
    OpenAIError,
    AnthropicError,
    GeminiError,
    NetworkError,
    RateLimitError,
    # File System
    FileSystemError,
    FileLoadError,
    FileWriteError,
    DirectoryError,
    # Resources
    ResourceError,
    MemoryError,
    DependencyError,
    # Operations
    OperationalError,
    AgentExecutionError,
    TemplateRenderingError,
)

# Rename base exception for compatibility
AgentActionsException = AgentActionsError

# Backward compatibility aliases
ProcessorError = ProcessingError
LoaderError = FileSystemError
DataParseError = ValidationError
UnsupportedFormatError = ValidationError

__all__ = [
    # Base (with alias)
    "AgentActionsError",
    "AgentActionsException",  # Alias
    # Common
    "InvalidParameterError",
    # Configuration
    "ConfigurationError",
    "ConfigValidationError",
    "DuplicateFunctionError",
    "FunctionNotFoundError",
    "UDFLoadError",
    "AgentNotFoundError",
    "ProjectNotFoundError",
    "EnvironmentConfigError",
    # Validation
    "ValidationError",
    "PromptValidationError",
    "DataValidationError",
    "SchemaValidationError",
    # Processing
    "ProcessingError",
    "TransformationError",
    "GenerationError",
    "WorkflowError",
    "SerializationError",
    # External Services
    "ExternalServiceError",
    "VendorAPIError",
    "OpenAIError",
    "AnthropicError",
    "GeminiError",
    "NetworkError",
    "RateLimitError",
    # File System
    "FileSystemError",
    "FileLoadError",
    "FileWriteError",
    "DirectoryError",
    # Resources
    "ResourceError",
    "MemoryError",
    "DependencyError",
    # Operations
    "OperationalError",
    "AgentExecutionError",
    "TemplateRenderingError",
    # Backward compatibility aliases
    "ProcessorError",
    "LoaderError",
    "DataParseError",
    "UnsupportedFormatError",
]
