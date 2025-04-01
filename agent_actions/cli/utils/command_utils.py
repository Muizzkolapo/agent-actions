"""
Command utilities for the Agent Actions CLI.

This module provides base classes and utilities for CLI commands
to reduce code redundancy and standardize patterns.
"""

import logging
import click
import os
import re
from typing import Any, Dict, Optional, List, Tuple
from pathlib import Path

from agent_actions.cli.exceptions import ValidationError, PermissionError


class BaseCommand:
    """Base class for all CLI commands."""
    
    # Common validation patterns
    PROJECT_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_-]*$')
    
    def __init__(self):
        """Initialize the base command with logging."""
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def handle_error(self, error: Exception, context: str, 
                    raise_click_exception: bool = True) -> None:
        """
        Common error handling pattern for commands.
        
        Args:
            error: The exception that occurred
            context: Description of what was being attempted
            raise_click_exception: Whether to raise a ClickException
        """
        self.logger.error(f"{context}: {str(error)}", exc_info=True)
        if raise_click_exception:
            raise click.ClickException(f"{context}: {str(error)}")
    
    def validate_path(self, path: Path, must_exist: bool = True, 
                     must_be_writable: bool = False, must_be_readable: bool = False,
                     must_be_directory: bool = False) -> None:
        """
        Validate a path for common requirements.
        
        Args:
            path: Path to validate
            must_exist: Whether the path must exist
            must_be_writable: Whether the path must be writable
            must_be_readable: Whether the path must be readable
            must_be_directory: Whether the path must be a directory
            
        Raises:
            ValidationError: If validation fails
        """
        if must_exist and not path.exists():
            raise ValidationError(f"Path does not exist: {path}")
        
        if must_be_writable and not os.access(path, os.W_OK):
            raise PermissionError(f"Path is not writable: {path}")
            
        if must_be_readable and not os.access(path, os.R_OK):
            raise PermissionError(f"Path is not readable: {path}")
            
        if must_be_directory and not path.is_dir():
            raise ValidationError(f"Path is not a directory: {path}")
    
    def get_agent_name(self, agent: str) -> str:
        """
        Extract agent name from agent configuration parameter.
        
        Args:
            agent: Agent configuration parameter (with or without extension)
            
        Returns:
            Agent name without extension
        """
        return Path(agent).stem
    
    def validate_agent_name(self, name: str, reserved_names: Optional[List[str]] = None) -> None:
        """
        Validate an agent name against common rules.
        
        Args:
            name: Name to validate
            reserved_names: Optional list of reserved names that cannot be used
            
        Raises:
            ValidationError: If the name is invalid
        """
        if not name:
            raise ValidationError("Name cannot be empty")
        
        if not self.PROJECT_NAME_PATTERN.match(name):
            raise ValidationError(
                f"Invalid name: {name}. "
                "Names must start with a letter and contain only "
                "letters, numbers, underscores, and hyphens."
            )
        
        if reserved_names and name.lower() in reserved_names:
            raise ValidationError(
                f"'{name}' is a reserved name and cannot be used"
            )
    
    def confirm_action(self, message: str, force: bool = False) -> bool:
        """
        Confirm an action with the user.
        
        Args:
            message: Message to display to the user
            force: Whether to skip confirmation
            
        Returns:
            True if confirmed or forced, False otherwise
        """
        if force:
            return True
        return click.confirm(message, default=False)
    
    def print_success(self, message: str) -> None:
        """
        Print a success message to the user.
        
        Args:
            message: Success message to display
        """
        click.echo(f"Successfully {message}")
    
    def print_warning(self, message: str) -> None:
        """
        Print a warning message to the user.
        
        Args:
            message: Warning message to display
        """
        click.echo(f"Warning: {message}")
    
    def print_error(self, message: str) -> None:
        """
        Print an error message to the user.
        
        Args:
            message: Error message to display
        """
        click.echo(f"Error: {message}", err=True)


class LoggingUtils:
    """Utility class for standardized logging patterns."""
    
    @staticmethod
    def log_command_start(logger: logging.Logger, command_name: str, **kwargs) -> None:
        """
        Log the start of a command execution.
        
        Args:
            logger: Logger instance
            command_name: Name of the command being executed
            **kwargs: Additional context to log
        """
        logger.info(f"Starting {command_name}", extra=kwargs)
    
    @staticmethod
    def log_command_success(logger: logging.Logger, command_name: str, **kwargs) -> None:
        """
        Log successful command completion.
        
        Args:
            logger: Logger instance
            command_name: Name of the command that completed
            **kwargs: Additional context to log
        """
        logger.info(f"Successfully completed {command_name}", extra=kwargs)
    
    @staticmethod
    def log_validation_start(logger: logging.Logger, validation_type: str, **kwargs) -> None:
        """
        Log the start of a validation process.
        
        Args:
            logger: Logger instance
            validation_type: Type of validation being performed
            **kwargs: Additional context to log
        """
        logger.info(f"Starting {validation_type} validation...", extra=kwargs)
    
    @staticmethod
    def log_validation_success(logger: logging.Logger, validation_type: str, **kwargs) -> None:
        """
        Log successful validation completion.
        
        Args:
            logger: Logger instance
            validation_type: Type of validation that completed
            **kwargs: Additional context to log
        """
        logger.info(f"Successfully completed {validation_type} validation", extra=kwargs)
    
    @staticmethod
    def log_config_operation(logger: logging.Logger, operation: str, **kwargs) -> None:
        """
        Log configuration-related operations.
        
        Args:
            logger: Logger instance
            operation: Description of the configuration operation
            **kwargs: Additional context to log
        """
        logger.info(f"Configuration {operation}...", extra=kwargs)
    
    @staticmethod
    def log_file_operation(logger: logging.Logger, operation: str, file_path: Path, **kwargs) -> None:
        """
        Log file-related operations.
        
        Args:
            logger: Logger instance
            operation: Description of the file operation
            file_path: Path to the file being operated on
            **kwargs: Additional context to log
        """
        logger.info(f"File {operation}: {file_path}", extra=kwargs) 