"""Centralized error exports for agent-actions."""

# Base error
from agent_actions.errors.base import (
    AgentActionsError,
    enrich_exception_context,
    get_error_detail,
)

# Configuration errors
from agent_actions.errors.configuration import (
    AgentNotFoundError,
    ConfigurationError,
    ConfigValidationError,
    DuplicateFunctionError,
    FunctionNotFoundError,
    ProjectNotFoundError,
    RecordContextError,
    UDFLoadError,
)

# External service errors
from agent_actions.errors.external_services import (
    AnthropicError,
    ExternalServiceError,
    LLMResponseParseError,
    NetworkError,
    PromptTooLargeError,
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
    "enrich_exception_context",
    "get_error_detail",
    # Configuration
    "ConfigurationError",
    "ConfigValidationError",
    "DuplicateFunctionError",
    "FunctionNotFoundError",
    "UDFLoadError",
    "AgentNotFoundError",
    "ProjectNotFoundError",
    "RecordContextError",
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
    "EmptyOutputError",
    # External Services
    "ExternalServiceError",
    "VendorAPIError",
    "AnthropicError",
    "NetworkError",
    "RateLimitError",
    "PromptTooLargeError",
    "LLMResponseParseError",
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
