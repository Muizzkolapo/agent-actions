"""Logger factory for centralized logging configuration."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from agent_actions.logging.config import HandlerConfig, LoggingConfig
from agent_actions.logging.filters import ContextInjectingFilter, RedactingFilter
from agent_actions.logging.formatters import HumanFormatter, JSONFormatter, SimpleFormatter


class LoggerFactory:
    """Factory for creating and configuring loggers.

    This class provides centralized logging configuration for the Agent Actions
    framework. It ensures all loggers share consistent configuration including
    formatters, filters, and handlers.

    Example:
        >>> LoggerFactory.initialize()
        >>> logger = LoggerFactory.get_logger('my_module')
        >>> logger.info('Hello world')  # Logs with context injection

    The factory is a singleton - calling initialize() multiple times will
    only configure logging once unless force=True is passed.
    """

    _initialized: bool = False
    _config: Optional[LoggingConfig] = None
    _root_logger_name: str = 'agent_actions'

    @classmethod
    def initialize(
        cls,
        config: Optional[LoggingConfig] = None,
        force: bool = False,
    ) -> None:
        """Initialize the logging system with configuration.

        Args:
            config: LoggingConfig instance. If None, uses defaults from environment.
            force: If True, reinitialize even if already initialized.
        """
        if cls._initialized and not force:
            return

        cls._config = config or LoggingConfig.from_environment()

        # Get root logger for agent_actions
        root_logger = logging.getLogger(cls._root_logger_name)

        # Set root logger level to most permissive of console and file
        # This ensures handlers can filter independently
        min_level = cls._config.default_level
        if cls._config.file_handler_enabled and cls._config.file_log_level:
            # Convert level names to numbers for comparison
            console_level_num = getattr(logging, cls._config.default_level)
            file_level_num = getattr(logging, cls._config.file_log_level)
            # Lower number = more permissive (DEBUG=10, INFO=20, etc.)
            min_level_num = min(console_level_num, file_level_num)
            # Convert back to name
            min_level = logging.getLevelName(min_level_num)

        root_logger.setLevel(getattr(logging, min_level))

        # Clear existing handlers to avoid duplicates
        root_logger.handlers.clear()

        # Clear any existing filters on root logger
        for f in root_logger.filters[:]:
            root_logger.removeFilter(f)

        # Configure handlers from config
        # Note: Filters are added to handlers (not logger) because Python's logging
        # doesn't inherit filters through the logger hierarchy
        if cls._config.handlers:
            for handler_config in cls._config.handlers:
                handler = cls._create_handler(handler_config)
                cls._add_filters_to_handler(handler)
                root_logger.addHandler(handler)
        else:
            # Add default console handler if none configured
            handler = cls._create_default_handler()
            cls._add_filters_to_handler(handler)
            root_logger.addHandler(handler)

        # Add file handler if enabled (independent of config.handlers)
        if cls._config.file_handler_enabled:
            file_handler = cls._create_file_handler()
            if file_handler:
                cls._add_filters_to_handler(file_handler)
                root_logger.addHandler(file_handler)

        # Configure module-specific levels
        for module, level in cls._config.module_levels.items():
            module_logger = logging.getLogger(module)
            module_logger.setLevel(getattr(logging, level))

        # Prevent propagation to root logger to avoid duplicate messages
        root_logger.propagate = False

        cls._initialized = True

    @classmethod
    def _create_handler(cls, config: HandlerConfig) -> logging.Handler:
        """Create a handler from configuration.

        Args:
            config: HandlerConfig specifying handler type and settings.

        Returns:
            Configured logging.Handler instance.
        """
        # Create the handler based on type
        if config.type == 'console':
            handler = logging.StreamHandler()
        elif config.type == 'file':
            if config.file_path is None:
                raise ValueError('file_path is required for file handler')
            handler = RotatingFileHandler(
                config.file_path,
                maxBytes=config.max_bytes,
                backupCount=config.backup_count,
            )
        elif config.type == 'json':
            handler = logging.StreamHandler()
        else:
            raise ValueError(f'Unknown handler type: {config.type}')

        # Set handler level
        handler.setLevel(getattr(logging, config.level))

        # Set formatter based on format config
        if config.format == 'json' or config.type == 'json':
            formatter = JSONFormatter(
                include_source_location=cls._config.include_source_location
                if cls._config
                else False,
            )
        elif config.type == 'file':
            # Use simple formatter for file output (no colors)
            formatter = SimpleFormatter(
                include_timestamp=cls._config.include_timestamps if cls._config else True,
            )
        else:
            # Console handler - use config setting for source location
            formatter = HumanFormatter(
                use_colors=True,
                include_source_location=cls._config.include_source_location
                if cls._config
                else False,
            )

        handler.setFormatter(formatter)

        return handler

    @classmethod
    def _create_default_handler(cls) -> logging.Handler:
        """Create the default console handler.

        Returns:
            Console handler with human-readable formatting.
        """
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)  # Let logger level control filtering

        formatter = HumanFormatter(
            use_colors=True,
            include_source_location=False,
        )
        handler.setFormatter(formatter)

        return handler

    @classmethod
    def _get_project_root(cls) -> Optional[Path]:
        """Find the project config directory.

        Walks up the directory tree looking for agent_actions.yml.
        Returns the directory containing the config file (where logs should go).

        Returns:
            Path to directory containing agent_actions.yml, or None if not found.
        """
        # Start from current working directory
        current = Path.cwd()

        # Walk up the directory tree looking for agent_actions.yml
        for parent in [current] + list(current.parents):
            if (parent / 'agent_actions.yml').exists():
                return parent

        return None

    @classmethod
    def _get_log_file_path(cls) -> Optional[Path]:
        """Determine the log file path based on configuration and environment.

        Priority order:
        1. config.log_file_path (if set)
        2. <agent_actions.yml_dir>/logs/agent_actions.log (if in project)
        3. ~/.agent-actions/logs/agent_actions.log (fallback)

        The logs folder is placed at the same level as agent_actions.yml.

        Returns:
            Path to log file, or None if file logging is disabled.
        """
        if not cls._config or not cls._config.file_handler_enabled:
            return None

        # Check if path is explicitly configured
        if cls._config.log_file_path:
            path = Path(cls._config.log_file_path)
            # If relative path, resolve relative to project root (or cwd)
            if not path.is_absolute():
                project_root = cls._get_project_root()
                if project_root:
                    path = project_root / path
                else:
                    path = Path.cwd() / path
            return path

        # Try to use project root
        project_root = cls._get_project_root()
        if project_root:
            return project_root / 'logs' / 'agent_actions.log'

        # Fallback to home directory
        return Path.home() / '.agent-actions' / 'logs' / 'agent_actions.log'

    @classmethod
    def _create_file_handler(cls) -> Optional[RotatingFileHandler]:
        """Create a rotating file handler for logging.

        Creates log directory if needed and configures rotation based on
        config.file_max_bytes and config.file_backup_count.

        Returns:
            RotatingFileHandler instance, or None if creation failed.
        """
        if not cls._config or not cls._config.file_handler_enabled:
            return None

        try:
            log_file_path = cls._get_log_file_path()
            if not log_file_path:
                return None

            # Create log directory if it doesn't exist
            log_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Create rotating file handler
            handler = RotatingFileHandler(
                filename=str(log_file_path),
                maxBytes=cls._config.file_max_bytes,
                backupCount=cls._config.file_backup_count,
                encoding='utf-8',
            )

            # Set handler level
            handler.setLevel(getattr(logging, cls._config.file_log_level))

            # Set formatter (no colors for file output)
            # Use config setting for source location
            if cls._config.file_format == 'json':
                formatter = JSONFormatter(
                    include_source_location=cls._config.include_source_location
                )
            else:
                formatter = HumanFormatter(
                    use_colors=False,
                    include_source_location=cls._config.include_source_location,
                )

            handler.setFormatter(formatter)

            # Log success to stderr only in DEBUG mode
            # (not to the logging system to avoid recursion)
            if cls._config and cls._config.default_level == 'DEBUG':
                print(f'Logging to file: {log_file_path}', file=sys.stderr)

            return handler

        except (OSError, IOError, ValueError) as e:
            # Log warning to stderr and continue without file handler
            print(
                f'Warning: Failed to create file handler: {e}. '
                'Continuing with console logging only.',
                file=sys.stderr,
            )
            return None

    @classmethod
    def _add_filters_to_handler(cls, handler: logging.Handler) -> None:
        """Add context injection and redacting filters to a handler.

        Args:
            handler: The handler to add filters to.
        """
        # Add context injection filter first
        handler.addFilter(ContextInjectingFilter())

        # Add redacting filter if patterns are configured
        if cls._config and cls._config.redact_patterns:
            handler.addFilter(RedactingFilter(patterns=cls._config.redact_patterns))

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger with the given name.

        The logger will be configured with context injection and consistent
        formatting. If initialize() hasn't been called, it will be called
        with default configuration.

        Args:
            name: Logger name. Will be prefixed with 'agent_actions.' if not
                  already under that namespace.

        Returns:
            Configured logging.Logger instance.
        """
        if not cls._initialized:
            cls.initialize()

        # Ensure logger is under agent_actions namespace
        if not name.startswith(cls._root_logger_name):
            name = f'{cls._root_logger_name}.{name}'

        return logging.getLogger(name)

    @classmethod
    def set_level(cls, level: str, logger_name: Optional[str] = None) -> None:
        """Set log level for a logger.

        Args:
            level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            logger_name: Logger name to set level for. If None, sets root level.
        """
        if not cls._initialized:
            cls.initialize()

        if logger_name:
            if not logger_name.startswith(cls._root_logger_name):
                logger_name = f'{cls._root_logger_name}.{logger_name}'
            logger = logging.getLogger(logger_name)
        else:
            logger = logging.getLogger(cls._root_logger_name)

        logger.setLevel(getattr(logging, level.upper()))

    @classmethod
    def set_debug(cls, debug: bool = True) -> None:
        """Enable or disable debug logging globally.

        Args:
            debug: If True, set level to DEBUG. If False, set to INFO.
        """
        level = 'DEBUG' if debug else 'INFO'
        cls.set_level(level)

    @classmethod
    def get_config(cls) -> Optional[LoggingConfig]:
        """Get the current logging configuration.

        Returns:
            Current LoggingConfig or None if not initialized.
        """
        return cls._config

    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the factory has been initialized.

        Returns:
            True if initialize() has been called.
        """
        return cls._initialized

    @classmethod
    def reset(cls) -> None:
        """Reset the factory state.

        This clears the initialized flag and config, useful for testing.
        Note: This does not remove handlers from existing loggers.
        """
        cls._initialized = False
        cls._config = None

        # Clear handlers from root logger
        root_logger = logging.getLogger(cls._root_logger_name)
        root_logger.handlers.clear()
        # Clear filters
        for f in root_logger.filters[:]:
            root_logger.removeFilter(f)
