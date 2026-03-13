"""Centralized error exports for agent-actions."""

# Base error
from agent_actions.errors.base import AgentActionsError, get_error_detail

# Common errors
from agent_actions.errors.common import InvalidParameterError

# Configuration errors
from agent_actions.errors.configuration import (
    AgentNotFoundError,
    ConfigurationError,
    ConfigValidationError,
    DuplicateFunctionError,
    FunctionNotFoundError,
    ProjectNotFoundError,
    UDFLoadError,
)

# External service errors
from agent_actions.errors.external_services import (
    AnthropicError,
    ExternalServiceError,
    NetworkError,
    RateLimitError,
    VendorAPIError,
)

# File system errors
from agent_actions.errors.filesystem import (
    DirectoryError,
    FileLoadError,
    FileSystemError,
    FileWriteError,
)

# Operational errors
from agent_actions.errors.operations import (
    AgentExecutionError,
    OperationalError,
    TemplateRenderingError,
    TemplateVariableError,
)

# Pre-flight validation errors
from agent_actions.errors.preflight import (
    ContextStructureError,
    PathValidationError,
    PreFlightValidationError,
    VendorConfigError,
)

# Processing errors
from agent_actions.errors.processing import (
    EmptyOutputError,
    GenerationError,
    ProcessingError,
    SerializationError,
    TransformationError,
    WorkflowError,
)

# Resource errors
from agent_actions.errors.resources import (
    DependencyError,
    ResourceError,
)

# Validation errors
from agent_actions.errors.validation import (
    DataValidationError,
    PromptValidationError,
    SchemaValidationError,
    ValidationError,
)

__all__ = [
    # Base
    "AgentActionsError",
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
