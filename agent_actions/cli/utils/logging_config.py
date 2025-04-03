"""
Logging configuration for the CLI module.

This module provides a centralized configuration for application logging,
using a class-based approach that follows SOLID principles.
"""

import logging
import logging.handlers
import os
import json
from pathlib import Path
from typing import Dict, Optional, Union, Any, List
from abc import ABC, abstractmethod


# Configuration constants
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DEFAULT_CONSOLE_FORMAT = '%(levelname)s: %(message)s'
DEFAULT_LOG_DIR = "logs"
DEFAULT_LOG_FILE = "agent_actions.log"
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB
BACKUP_COUNT = 5


class LogFormatter(ABC):
    """Abstract base class for log formatters."""
    
    @abstractmethod
    def create_formatter(self) -> logging.Formatter:
        """Create and return a formatter instance."""
        pass


class StandardFormatter(LogFormatter):
    """Standard text formatter for logs."""
    
    def __init__(self, format_string: str = DEFAULT_LOG_FORMAT):
        self.format_string = format_string
        
    def create_formatter(self) -> logging.Formatter:
        return logging.Formatter(self.format_string)


class JSONFormatter(LogFormatter):
    """JSON formatter for structured logging."""
    
    def create_formatter(self) -> logging.Formatter:
        return _JSONFormatter()


class _JSONFormatter(logging.Formatter):
    """Implementation of JSON formatter."""
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format the log record as a JSON string.
        
        Args:
            record: The log record to format.
            
        Returns:
            A JSON-formatted string containing the log record.
        """
        log_data = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add any extra attributes
        for key, value in record.__dict__.items():
            if key not in ['args', 'asctime', 'created', 'exc_info', 'exc_text', 
                          'filename', 'funcName', 'id', 'levelname', 'levelno',
                          'lineno', 'module', 'msecs', 'message', 'msg', 
                          'name', 'pathname', 'process', 'processName', 
                          'relativeCreated', 'stack_info', 'thread', 'threadName']:
                log_data[key] = value
                
        # Handle exceptions
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)


class LogHandler(ABC):
    """Abstract base class for log handlers."""
    
    def __init__(self, log_level: int, formatter: LogFormatter):
        self.log_level = log_level
        self.formatter = formatter
    
    @abstractmethod
    def create_handler(self) -> logging.Handler:
        """Create and return a configured handler."""
        pass


class ConsoleHandler(LogHandler):
    """Handler for console logging."""
    
    def create_handler(self) -> logging.Handler:
        handler = logging.StreamHandler()
        formatter = self.formatter.create_formatter()
        handler.setFormatter(formatter)
        handler.setLevel(self.log_level)
        return handler


class RotatingFileHandler(LogHandler):
    """Handler for rotating file logging."""
    
    def __init__(self, log_level: int, formatter: LogFormatter, 
                 file_path: str, max_bytes: int, backup_count: int):
        super().__init__(log_level, formatter)
        self.file_path = file_path
        self.max_bytes = max_bytes
        self.backup_count = backup_count
    
    def create_handler(self) -> logging.Handler:
        try:
            handler = logging.handlers.RotatingFileHandler(
                self.file_path,
                maxBytes=self.max_bytes,
                backupCount=self.backup_count,
                encoding='utf-8'
            )
            formatter = self.formatter.create_formatter()
            handler.setFormatter(formatter)
            handler.setLevel(self.log_level)
            return handler
        except Exception as e:
            raise RuntimeError(f"Failed to set up file logging handler: {str(e)}") from e


class LogLevelResolver:
    """Resolves string log level names to numeric values."""
    
    @staticmethod
    def get_level(level_name: str) -> int:
        """
        Convert a string log level to the corresponding logging level.
        
        Args:
            level_name: The name of the log level (e.g., "INFO", "DEBUG").
            
        Returns:
            The numeric logging level.
            
        Raises:
            ValueError: If the provided level name is not valid.
        """
        level_name = level_name.upper()
        if hasattr(logging, level_name):
            return getattr(logging, level_name)
        
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        raise ValueError(f"Invalid log level: {level_name}. Valid levels are: {', '.join(valid_levels)}")


class LogDirectoryManager:
    """Manages log directory creation."""
    
    @staticmethod
    def create_directory(log_dir: Union[str, Path]) -> Path:
        """
        Create the log directory if it doesn't exist.
        
        Args:
            log_dir: Path to the log directory.
            
        Returns:
            Path object pointing to the log directory.
            
        Raises:
            OSError: If the directory cannot be created.
        """
        log_path = Path(log_dir)
        try:
            log_path.mkdir(parents=True, exist_ok=True)
            return log_path
        except OSError as e:
            raise OSError(f"Failed to create log directory {log_dir}: {str(e)}") from e


class LoggingConfigurator:
    """Configures logging for the application."""
    
    def __init__(self):
        # Default configuration
        self.log_level = DEFAULT_LOG_LEVEL
        self.log_dir = DEFAULT_LOG_DIR
        self.log_file = None
        self.use_json = False
        self.console_level = None
        self.handlers = []
    
    def with_level(self, log_level: str) -> 'LoggingConfigurator':
        """Set the log level."""
        self.log_level = log_level
        return self
    
    def with_log_dir(self, log_dir: str) -> 'LoggingConfigurator':
        """Set the log directory."""
        self.log_dir = log_dir
        return self
    
    def with_log_file(self, log_file: str) -> 'LoggingConfigurator':
        """Set the log file."""
        self.log_file = log_file
        return self
    
    def with_json_formatting(self, use_json: bool = True) -> 'LoggingConfigurator':
        """Enable or disable JSON formatting."""
        self.use_json = use_json
        return self
    
    def with_console_level(self, console_level: str) -> 'LoggingConfigurator':
        """Set the console log level."""
        self.console_level = console_level
        return self
    
    def setup(self) -> Dict[str, Any]:
        """
        Set up logging with the configured settings.
        
        Returns:
            Dictionary with logging configuration details.
            
        Raises:
            ValueError: If invalid log levels are provided.
            OSError: If log directory cannot be created.
            RuntimeError: If handlers cannot be set up.
        """
        try:
            # Resolve log levels
            file_log_level = LogLevelResolver.get_level(self.log_level)
            
            if self.console_level is None:
                # If main log level is DEBUG, show INFO in console, otherwise show WARNING
                console_log_level = logging.INFO if self.log_level.upper() == "DEBUG" else logging.WARNING
            else:
                console_log_level = LogLevelResolver.get_level(self.console_level)
            
            # Set up the root logger
            root_logger = logging.getLogger()
            root_logger.setLevel(file_log_level)
            
            # Clear any existing handlers to avoid duplicate logs
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)
            
            # Resolve log file path
            if self.log_file is None:
                log_dir_path = LogDirectoryManager.create_directory(self.log_dir)
                self.log_file = str(log_dir_path / DEFAULT_LOG_FILE)
            
            # Initialize handlers
            handler_objects = {}
            
            # Create formatters
            file_formatter = JSONFormatter() if self.use_json else StandardFormatter()
            console_formatter = StandardFormatter(DEFAULT_CONSOLE_FORMAT)
            
            # Set up file handler
            file_handler_factory = RotatingFileHandler(
                file_log_level, 
                file_formatter,
                self.log_file,
                MAX_LOG_SIZE,
                BACKUP_COUNT
            )
            file_handler = file_handler_factory.create_handler()
            root_logger.addHandler(file_handler)
            handler_objects['file'] = file_handler
            
            # Set up console handler
            console_handler_factory = ConsoleHandler(console_log_level, console_formatter)
            console_handler = console_handler_factory.create_handler()
            root_logger.addHandler(console_handler)
            handler_objects['console'] = console_handler
            
            # Log configuration success at DEBUG level to avoid showing it by default
            logging.debug("Logging configured successfully", extra={
                'log_file': self.log_file,
                'log_level': self.log_level,
                'console_level': self.console_level or "AUTO",
                'use_json': self.use_json
            })
            
            return {
                'log_file': self.log_file,
                'file_level': logging.getLevelName(file_log_level),
                'console_level': logging.getLevelName(console_log_level),
                'handlers': handler_objects,
                'use_json': self.use_json
            }
        except Exception as e:
            # If we can't set up logging properly, at least try to output to console
            print(f"ERROR: Failed to configure logging: {str(e)}")
            raise RuntimeError(f"Failed to configure logging: {str(e)}") from e


def setup_logging(
    log_level: str = DEFAULT_LOG_LEVEL, 
    log_file: Optional[str] = None,
    log_dir: str = DEFAULT_LOG_DIR,
    use_json: bool = False,
    console_level: Optional[str] = None
) -> Dict[str, Any]:
    """
    Set up logging configuration with both file and console handlers.
    
    This function provides backward compatibility with the original API.
    
    Args:
        log_level: The logging level to use (default: INFO)
        log_file: Optional path to the log file. If None, will use default location.
        log_dir: Directory to store log files (default: logs)
        use_json: Whether to use JSON formatting for file logs
        console_level: Optional separate log level for console output.
            If None, will use WARNING or INFO based on log_level.
            
    Returns:
        Dictionary with logging configuration details.
    """
    configurator = LoggingConfigurator()
    
    # Apply configuration
    configurator.with_level(log_level)
    
    if log_file:
        configurator.with_log_file(log_file)
    else:
        configurator.with_log_dir(log_dir)
        
    if use_json:
        configurator.with_json_formatting()
        
    if console_level:
        configurator.with_console_level(console_level)
        
    # Set up logging
    return configurator.setup()