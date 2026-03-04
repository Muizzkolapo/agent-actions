"""
Centralized error exports for agent-actions.
"""

# Base error
from agent_actions.errors.base import AgentActionsError, get_error_detail

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
    EmptyOutputError,
)

# External service errors
from agent_actions.errors.external_services import (
    ExternalServiceError,
    VendorAPIError,
    AnthropicError,
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
    DependencyError,
)

# Operational errors
from agent_actions.errors.operations import (
    OperationalError,
    AgentExecutionError,
    TemplateRenderingError,
    TemplateVariableError,
)

# Pre-flight validation errors
from agent_actions.errors.preflight import (
    PreFlightValidationError,
    ContextStructureError,
    VendorConfigError,
    PathValidationError,
)

# Backward compatibility aliases
AgentActionsException = AgentActionsError  # Deprecated: use AgentActionsError directly

__all__ = [
    # Base
    "AgentActionsError",
    "AgentActionsException",  # Alias for backward compatibility
    "get_error_detail",
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
    "EmptyOutputError",
    # External Services
    "ExternalServiceError",
    "VendorAPIError",
    "AnthropicError",
    "NetworkError",
    "RateLimitError",
    # File System
    "FileSystemError",
    "FileLoadError",
    "FileWriteError",
    "DirectoryError",
    # Resources
    "ResourceError",
    "DependencyError",
    # Operations
    "OperationalError",
    "AgentExecutionError",
    "TemplateRenderingError",
    "TemplateVariableError",
    # Pre-flight validation
    "PreFlightValidationError",
    "ContextStructureError",
    "VendorConfigError",
    "PathValidationError",
]
