"""
Core exception handling system for Agent Actions.

This module defines a comprehensive exception hierarchy that provides:
1. Structured error codes and categories
2. Consistent error reporting
3. Recovery suggestions
4. Contextual information capture
5. CLI integration
"""

import enum
import json
import traceback
import sys
from typing import Dict, List, Optional, Any, NoReturn, Union
from dataclasses import dataclass, field, asdict


class ExitCode(enum.IntEnum):
    """Exit codes for command-line operations."""
    SUCCESS = 0
    GENERAL_ERROR = 1
    CONFIG_ERROR = 2
    USER_ERROR = 3
    WORKFLOW_ERROR = 4
    FILE_ERROR = 5
    DEPENDENCY_ERROR = 6
    UNHANDLED_ERROR = 100


class ErrorCategory(enum.Enum):
    """Categories of errors for organization and filtering."""
    SYSTEM = "system"           # OS, hardware, environment issues
    CONFIGURATION = "config"    # Issues with configuration files/format
    WORKFLOW = "workflow"       # Issues with agent workflows
    USER_CODE = "user_code"     # Issues with user-provided code
    FILE_SYSTEM = "filesystem"  # Issues with file operations
    NETWORK = "network"         # Issues with network operations
    SECURITY = "security"       # Security-related issues
    VALIDATION = "validation"   # Data validation issues
    EXECUTION = "execution"     # Issues during execution of agents
    UNKNOWN = "unknown"         # Uncategorized errors


@dataclass
class ErrorContext:
    """Contextual information about an error occurrence."""
    
    # Basic information
    message: str
    error_code: str
    category: ErrorCategory
    
    # Additional context
    details: Dict[str, Any] = field(default_factory=dict)
    recovery_hint: Optional[str] = None
    traceback_str: Optional[str] = None
    exit_code: ExitCode = ExitCode.GENERAL_ERROR
    
    def __post_init__(self):
        """Capture traceback if not provided."""
        if self.traceback_str is None:
            self.traceback_str = traceback.format_exc()
            
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        # Convert enums to strings for serialization
        result['category'] = self.category.value
        result['exit_code'] = self.exit_code.value
        return result
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)
    
    def format_message(self, include_code: bool = True) -> str:
        """Format the error message with optional components."""
        parts = []
        
        # Add error code if requested
        if include_code:
            parts.append(f"[{self.error_code}]")
            
        # Always include the main message
        parts.append(self.message)
        
        # Add recovery hint if available
        if self.recovery_hint:
            parts.append(f"Hint: {self.recovery_hint}")
            
        return " ".join(parts)


class AgentError(Exception):
    """Base exception for all Agent Actions errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        details: Optional[Dict[str, Any]] = None,
        recovery_hint: Optional[str] = None,
        exit_code: ExitCode = ExitCode.GENERAL_ERROR,
        **kwargs
    ):
        """
        Initialize the exception with enhanced context.
        
        Args:
            message: Human-readable error message
            error_code: Unique identifier for this error type
            category: General category of the error
            details: Additional contextual details about the error
            recovery_hint: Suggestion for how to recover from this error
            exit_code: System exit code to use if this error terminates the program
            **kwargs: Additional context values to include in details
        """
        # Update details with any additional kwargs
        all_details = details or {}
        all_details.update(kwargs)
        
        # Create error context
        self.context = ErrorContext(
            message=message,
            error_code=error_code,
            category=category,
            details=all_details,
            recovery_hint=recovery_hint,
            exit_code=exit_code
        )
        
        # Call parent constructor with formatted message
        super().__init__(self.context.format_message())
        
    def __str__(self) -> str:
        """String representation of the exception."""
        return self.context.format_message()
    
    @property
    def error_code(self) -> str:
        """Get the error code."""
        return self.context.error_code
    
    @property
    def category(self) -> ErrorCategory:
        """Get the error category."""
        return self.context.category
    
    @property
    def details(self) -> Dict[str, Any]:
        """Get the error details."""
        return self.context.details
    
    @property
    def recovery_hint(self) -> Optional[str]:
        """Get the recovery hint."""
        return self.context.recovery_hint
    
    @property
    def exit_code(self) -> ExitCode:
        """Get the exit code."""
        return self.context.exit_code
    
    def exit(self) -> NoReturn:
        """Exit the program with the appropriate exit code."""
        sys.exit(self.context.exit_code)


# System Exceptions
class SystemError(AgentError):
    """Base class for system-level exceptions."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.SYSTEM,
            exit_code=ExitCode.GENERAL_ERROR,
            **kwargs
        )


class EnvironmentError(SystemError):
    """Exception raised when there's an issue with the execution environment."""
    
    def __init__(
        self,
        message: str,
        variable: Optional[str] = None,
        expected_value: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if variable:
            details["variable"] = variable
            details["current_value"] = sys.environ.get(variable, "Not set")
            if expected_value:
                details["expected_value"] = expected_value
                
        recovery_hint = f"Check environment variable {variable}" if variable else "Check your environment setup"
                
        super().__init__(
            message=message,
            error_code="ENV_ERROR",
            details=details,
            recovery_hint=recovery_hint,
            **kwargs
        )


# Configuration Exceptions
class ConfigError(AgentError):
    """Base class for configuration-related exceptions."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        config_path: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if config_path:
            details["config_path"] = config_path
            
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.CONFIGURATION,
            details=details,
            exit_code=ExitCode.CONFIG_ERROR,
            **kwargs
        )


class MissingConfigError(ConfigError):
    """Exception raised when a required configuration file is missing."""
    
    def __init__(
        self,
        config_path: str,
        **kwargs
    ):
        super().__init__(
            message=f"Missing configuration file: {config_path}",
            error_code="MISSING_CONFIG",
            config_path=config_path,
            recovery_hint=f"Ensure the configuration file exists at {config_path}",
            **kwargs
        )


class InvalidConfigError(ConfigError):
    """Exception raised when a configuration file has invalid format or content."""
    
    def __init__(
        self,
        config_path: str,
        reason: str,
        **kwargs
    ):
        super().__init__(
            message=f"Invalid configuration in {config_path}: {reason}",
            error_code="INVALID_CONFIG",
            config_path=config_path,
            reason=reason,
            recovery_hint="Check the configuration format and content",
            **kwargs
        )


class DuplicateConfigError(ConfigError):
    """Exception raised when duplicate configuration entries are found."""
    
    def __init__(
        self,
        config_path: str,
        duplicate_key: Optional[str] = None,
        **kwargs
    ):
        message = f"Duplicate configuration found: {config_path}"
        if duplicate_key:
            message += f" (key: {duplicate_key})"
            
        super().__init__(
            message=message,
            error_code="DUPLICATE_CONFIG",
            config_path=config_path,
            duplicate_key=duplicate_key,
            recovery_hint="Remove or rename one of the duplicate configurations",
            **kwargs
        )


class MissingSchemaError(ConfigError):
    """Exception raised when a required schema is missing."""
    
    def __init__(
        self,
        agent_name: str,
        schema_path: Optional[str] = None,
        **kwargs
    ):
        details = {"agent_name": agent_name}
        if schema_path:
            details["schema_path"] = schema_path
            
        super().__init__(
            message=f"Missing schema for agent: {agent_name}",
            error_code="MISSING_SCHEMA",
            details=details,
            recovery_hint="Ensure the required schema file is present in the schema directory",
            **kwargs
        )


# Workflow Exceptions
class WorkflowError(AgentError):
    """Base class for workflow-related exceptions."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        workflow_name: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if workflow_name:
            details["workflow_name"] = workflow_name
            
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.WORKFLOW,
            details=details,
            exit_code=ExitCode.WORKFLOW_ERROR,
            **kwargs
        )


class WorkflowDefinitionError(WorkflowError):
    """Exception raised when there's an issue with a workflow definition."""
    
    def __init__(
        self,
        workflow_name: str,
        reason: str,
        **kwargs
    ):
        super().__init__(
            message=f"Invalid workflow definition for {workflow_name}: {reason}",
            error_code="INVALID_WORKFLOW_DEF",
            workflow_name=workflow_name,
            reason=reason,
            recovery_hint="Check the workflow definition for errors",
            **kwargs
        )


class WorkflowExecutionError(WorkflowError):
    """Exception raised when there's an issue executing a workflow."""
    
    def __init__(
        self,
        workflow_name: str,
        step: Optional[str] = None,
        reason: str = "Execution failed",
        **kwargs
    ):
        message = f"Workflow execution failed for {workflow_name}"
        if step:
            message += f" at step '{step}'"
        message += f": {reason}"
        
        details = {"workflow_name": workflow_name, "reason": reason}
        if step:
            details["step"] = step
            
        super().__init__(
            message=message,
            error_code="WORKFLOW_EXECUTION_ERROR",
            details=details,
            recovery_hint="Check the logs for more details",
            **kwargs
        )


class WorkflowNameMismatchError(WorkflowError):
    """Exception raised when a workflow name doesn't match available workflows."""
    
    def __init__(
        self,
        requested_name: str,
        available_names: List[str],
        **kwargs
    ):
        super().__init__(
            message=f"Workflow name '{requested_name}' not found in available workflows",
            error_code="WORKFLOW_NAME_MISMATCH",
            workflow_name=requested_name,
            available_names=available_names,
            recovery_hint=f"Use one of the available workflow names: {', '.join(available_names)}",
            **kwargs
        )


# File System Exceptions
class FileSystemError(AgentError):
    """Base class for file system-related exceptions."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        path: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if path:
            details["path"] = path
            
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.FILE_SYSTEM,
            details=details,
            exit_code=ExitCode.FILE_ERROR,
            **kwargs
        )


class FileProcessingError(FileSystemError):
    """Exception raised when there's an issue processing a file."""
    
    def __init__(
        self,
        file_path: str,
        reason: str,
        **kwargs
    ):
        super().__init__(
            message=f"Error processing file '{file_path}': {reason}",
            error_code="FILE_PROCESSING_ERROR",
            path=file_path,
            reason=reason,
            recovery_hint="Check file permissions and contents",
            **kwargs
        )


class NoFilesFoundError(FileSystemError):
    """Exception raised when no files are found in a directory."""
    
    def __init__(
        self,
        directory: str,
        **kwargs
    ):
        super().__init__(
            message=f"No files found in directory: {directory}",
            error_code="NO_FILES_FOUND",
            path=directory,
            recovery_hint="Ensure that input files exist in the specified directory",
            **kwargs
        )


class DirectoryError(FileSystemError):
    """Exception raised when there's an issue with a directory."""
    
    def __init__(
        self,
        directory: str,
        reason: str = "Directory error",
        **kwargs
    ):
        super().__init__(
            message=f"{reason}: {directory}",
            error_code="DIRECTORY_ERROR",
            path=directory,
            reason=reason,
            recovery_hint="Verify that the directory exists and you have proper permissions",
            **kwargs
        )


# User Code Exceptions
class UserCodeError(AgentError):
    """Base class for exceptions related to user-provided code."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.USER_CODE,
            exit_code=ExitCode.USER_ERROR,
            **kwargs
        )


class UDFNotFoundError(UserCodeError):
    """Exception raised when a user-defined function is not found."""
    
    def __init__(
        self,
        function_name: str,
        module_name: str,
        **kwargs
    ):
        super().__init__(
            message=f"User-defined function '{function_name}' not found in module '{module_name}'",
            error_code="UDF_NOT_FOUND",
            function_name=function_name,
            module_name=module_name,
            recovery_hint=f"Ensure that function '{function_name}' exists in module '{module_name}'",
            **kwargs
        )


class UDFExecutionError(UserCodeError):
    """Exception raised when there's an issue executing a user-defined function."""
    
    def __init__(
        self,
        function_name: str,
        reason: str,
        **kwargs
    ):
        super().__init__(
            message=f"Error executing user-defined function '{function_name}': {reason}",
            error_code="UDF_EXECUTION_ERROR",
            function_name=function_name,
            reason=reason,
            recovery_hint="Check function implementation and input data",
            **kwargs
        )


# Project Initialization Exceptions
class ProjectError(AgentError):
    """Base class for project-related exceptions."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        project_name: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if project_name:
            details["project_name"] = project_name
            
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.SYSTEM,
            details=details,
            **kwargs
        )


class ProjectInitError(ProjectError):
    """Exception raised when there's an issue initializing a project."""
    
    def __init__(
        self,
        project_name: str,
        reason: str,
        **kwargs
    ):
        super().__init__(
            message=f"Error initializing project '{project_name}': {reason}",
            error_code="PROJECT_INIT_ERROR",
            project_name=project_name,
            reason=reason,
            recovery_hint="Check permissions and ensure the path is valid",
            **kwargs
        )


class CleanupError(ProjectError):
    """Exception raised when there's an issue cleaning up agent directories."""
    
    def __init__(
        self,
        agent_name: str,
        reason: str,
        **kwargs
    ):
        super().__init__(
            message=f"Error cleaning up agent '{agent_name}': {reason}",
            error_code="CLEANUP_ERROR",
            agent_name=agent_name,
            reason=reason,
            recovery_hint="Check permissions and ensure no processes are using the files",
            **kwargs
        )


# Documentation Exceptions
class DocumentationError(AgentError):
    """Base class for documentation-related exceptions."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.SYSTEM,
            **kwargs
        )


class DocsServerError(DocumentationError):
    """Exception raised when there's an issue with the documentation server."""
    
    def __init__(
        self,
        reason: str,
        **kwargs
    ):
        super().__init__(
            message=f"Documentation server error: {reason}",
            error_code="DOCS_SERVER_ERROR",
            reason=reason,
            recovery_hint="Check network configuration and ensure port is available",
            **kwargs
        )


class TemplateRenderError(DocumentationError):
    """Exception raised when there's an issue rendering a template."""
    
    def __init__(
        self,
        template_name: str,
        reason: str,
        **kwargs
    ):
        super().__init__(
            message=f"Error rendering template '{template_name}': {reason}",
            error_code="TEMPLATE_RENDER_ERROR",
            template_name=template_name,
            reason=reason,
            recovery_hint="Check template syntax and ensure all variables are defined",
            **kwargs
        )


# Unhandled and Internal Exceptions
class InternalError(AgentError):
    """Exception raised for internal errors that should never occur in normal operation."""
    
    def __init__(
        self,
        message: str,
        **kwargs
    ):
        super().__init__(
            message=f"Internal error: {message}",
            error_code="INTERNAL_ERROR",
            category=ErrorCategory.SYSTEM,
            exit_code=ExitCode.UNHANDLED_ERROR,
            recovery_hint="This is likely a bug. Please report it to the development team.",
            **kwargs
        )


class UnhandledError(AgentError):
    """Wrapper for unhandled exceptions."""
    
    def __init__(
        self,
        original_exception: Exception,
        **kwargs
    ):
        exc_type = type(original_exception).__name__
        exc_msg = str(original_exception)
        
        super().__init__(
            message=f"Unhandled {exc_type}: {exc_msg}",
            error_code="UNHANDLED_ERROR",
            category=ErrorCategory.UNKNOWN,
            exit_code=ExitCode.UNHANDLED_ERROR,
            original_exception=exc_type,
            original_message=exc_msg,
            **kwargs
        )


# CLI Integration
class CliError(AgentError):
    """Base exception for CLI-related errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        exit_code: ExitCode = ExitCode.GENERAL_ERROR,
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            exit_code=exit_code,
            **kwargs
        )


class CliUsageError(CliError):
    """Exception raised when there's an issue with CLI usage."""
    
    def __init__(
        self,
        message: str,
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code="CLI_USAGE_ERROR",
            category=ErrorCategory.USER_CODE,
            exit_code=ExitCode.USER_ERROR,
            **kwargs
        )


class CliResultError(CliError):
    """Exception that carries results from a CLI operation."""
    
    def __init__(
        self,
        message: str,
        result: Any,
        exit_code: ExitCode = ExitCode.GENERAL_ERROR,
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code="CLI_RESULT",
            exit_code=exit_code,
            **kwargs
        )
        self.result = result


class ValidationError(AgentError):
    """Exception raised when data validation fails."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "VALIDATION_ERROR",
        field_name: Optional[str] = None,
        expected_type: Optional[str] = None,
        **kwargs
    ):
        details = {}
        if field_name:
            details["field_name"] = field_name
        if expected_type:
            details["expected_type"] = expected_type
            
        super().__init__(
            message=message,
            error_code=error_code,
            category=ErrorCategory.VALIDATION,
            details=details,
            recovery_hint="Check the input data format and structure",
            **kwargs
        )