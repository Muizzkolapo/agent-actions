"""
Centralized error exports for agent-actions.
"""

# Base error
from agent_actions.errors.base import AgentActionsError

# Common errors
from agent_actions.errors.common import InvalidParameterError

# Configuration errors
from agent_actions.errors.configuration import (
    ConfigurationError,
    ConfigValidationError,
    DuplicateFunctionError,
    FunctionNotFoundError,
    UDFLoadError,
    AgentNotFoundError,
    ProjectNotFoundError,
    EnvironmentConfigError,
)

# Validation errors
from agent_actions.errors.validation import (
    ValidationError,
    PromptValidationError,
    DataValidationError,
    SchemaValidationError,
)

# Processing errors
from agent_actions.errors.processing import (
    ProcessingError,
    TransformationError,
    GenerationError,
    WorkflowError,
    SerializationError,
)

# External service errors
from agent_actions.errors.external_services import (
    ExternalServiceError,
    VendorAPIError,
    OpenAIError,
    AnthropicError,
    GeminiError,
    NetworkError,
    RateLimitError,
)

# File system errors
from agent_actions.errors.filesystem import (
    FileSystemError,
    FileLoadError,
    FileWriteError,
    DirectoryError,
)

# Resource errors
from agent_actions.errors.resources import (
    ResourceError,
    ResourceMemoryError,
    DependencyError,
)

# Operational errors
from agent_actions.errors.operations import (
    OperationalError,
    AgentExecutionError,
    TemplateRenderingError,
)

# Pre-flight validation errors
from agent_actions.errors.preflight import (
    PreFlightValidationError,
    TemplateVariableError,
    ContextStructureError,
    DependencyValidationError,
    VendorConfigError,
    PathValidationError,
)

# Backward compatibility aliases
AgentActionsException = AgentActionsError
ProcessorError = ProcessingError
LoaderError = FileSystemError
DataParseError = ValidationError
UnsupportedFormatError = ValidationError

__all__ = [
    # Base
    "AgentActionsError",
    "AgentActionsException",  # Alias for backward compatibility
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
    "ResourceMemoryError",
    "DependencyError",
    # Operations
    "OperationalError",
    "AgentExecutionError",
    "TemplateRenderingError",
    # Pre-flight validation
    "PreFlightValidationError",
    "TemplateVariableError",
    "ContextStructureError",
    "DependencyValidationError",
    "VendorConfigError",
    "PathValidationError",
    # Backward compatibility aliases
    "ProcessorError",
    "LoaderError",
    "DataParseError",
    "UnsupportedFormatError",
]
