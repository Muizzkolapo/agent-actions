"""
Logger factory for centralized logging configuration.

This module provides a unified logging system that routes ALL logging
through the event system. Python's standard logging (logger.info(), etc.)
is automatically bridged to events.

Architecture:
    Application Code
           │
           ├── logger.info("msg")  ──┐
           │                         │
           └── fire_event(Event)  ───┼──► EventManager
                                     │         │
                                     │    ┌────┴────┐
                                     │    │         │
                                     ▼    ▼         ▼
                              Console  JSON File  run_results.json
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from agent_actions.logging.config import LoggingConfig

if TYPE_CHECKING:
    from agent_actions.logging.core import EventManager
    from agent_actions.logging.core.handlers import ContextDebugHandler
    from agent_actions.logging.events.handlers import RunResultsCollector


class LoggerFactory:
    """
    Centralized logging factory using event-based architecture.

    All logging flows through the EventManager:
    - Python logging (logger.info()) → LoggingBridgeHandler → Events
    - Direct events (fire_event()) → Events
    - Events → Handlers (Console, JSON, run_results.json)

    Example:
        >>> LoggerFactory.initialize()
        >>> logger = LoggerFactory.get_logger('my_module')
        >>> logger.info('Hello world')  # → Becomes an event

    Or use events directly:
        >>> from agent_actions.logging import fire_event
        >>> from agent_actions.logging.events import WorkflowStartEvent
        >>> fire_event(WorkflowStartEvent(workflow_name="test"))
    """

    _initialized: bool = False
    _config: Optional[LoggingConfig] = None
    _root_logger_name: str = "agent_actions"
    _event_manager: Optional["EventManager"] = None
    _run_results_collector: Optional["RunResultsCollector"] = None

    @classmethod
    def initialize(
        cls,
        config: Optional[LoggingConfig] = None,
        output_dir: Optional[str | Path] = None,
        workflow_name: str = "",
        invocation_id: Optional[str] = None,
        verbose: bool = False,
        quiet: bool = False,
        force: bool = False,
    ) -> "EventManager":
        """
        Initialize the unified logging system.

        This sets up:
        - EventManager as the central dispatcher
        - LoggingBridgeHandler to convert Python logging to events
        - ConsoleEventHandler for user-facing output
        - JSONFileHandler for debug logs
        - RunResultsCollector for run_results.json artifact

        Args:
            config: LoggingConfig instance. If None, uses defaults from environment.
            output_dir: Directory for run_results.json and event logs
            workflow_name: Name of the workflow being executed
            invocation_id: Unique ID for this invocation (generated if not provided)
            verbose: Show DEBUG level events on console
            quiet: Only show WARN and ERROR events on console
            force: Reinitialize even if already initialized

        Returns:
            The initialized EventManager instance
        """
        if cls._initialized and not force:
            return cls._event_manager  # type: ignore

        # Load config
        cls._config = config or LoggingConfig.from_environment()

        # Determine log levels from config and flags
        if verbose or cls._config.default_level == "DEBUG":
            console_level_str = "DEBUG"
        elif quiet:
            console_level_str = "WARN"
        else:
            console_level_str = cls._config.default_level

        # Import event system components
        from agent_actions.logging.core import (
            ConsoleEventHandler,
            EventLevel,
            EventManager,
            JSONFileHandler,
        )
        from agent_actions.logging.core.handlers import LoggingBridgeHandler
        from agent_actions.logging.events import AgentActionsFormatter
        from agent_actions.logging.events.handlers import RunResultsCollector

        # Get or create event manager
        manager = EventManager.get()
        cls._event_manager = manager

        # On force re-init, flush buffered events then stash old handlers.
        # If setup below fails, we restore them so logging isn't left degraded.
        previous_handlers = None
        if force:
            manager.flush()
            previous_handlers = list(manager._handlers)
            manager.clear_handlers()

        try:
            cls._register_handlers(
                manager,
                config=cls._config,
                output_dir=output_dir,
                workflow_name=workflow_name,
                invocation_id=invocation_id,
                verbose=verbose,
                console_level_str=console_level_str,
            )
        except Exception:
            if previous_handlers is not None:
                manager.clear_handlers()
                for handler in previous_handlers:
                    manager.register(handler)
            raise

        # Setup Python logging bridge
        # This converts all logger.* calls to events
        cls._setup_logging_bridge()

        # Mark as initialized
        manager.initialize()
        cls._initialized = True

        return manager

    @classmethod
    def _register_handlers(
        cls,
        manager,
        *,
        config,
        output_dir,
        workflow_name,
        invocation_id,
        verbose,
        console_level_str,
    ) -> None:
        """Build and register all event handlers on the manager."""
        from agent_actions.logging.core import (
            ConsoleEventHandler,
            EventLevel,
            JSONFileHandler,
        )
        from agent_actions.logging.events import AgentActionsFormatter
        from agent_actions.logging.events.handlers import RunResultsCollector

        # Generate invocation ID if not provided
        if not invocation_id:
            invocation_id = str(uuid.uuid4())[:8]

        # Set context
        manager.set_context(
            invocation_id=invocation_id,
            workflow_name=workflow_name,
        )

        # Map string level to EventLevel
        level_map = {
            "DEBUG": EventLevel.DEBUG,
            "INFO": EventLevel.INFO,
            "WARN": EventLevel.WARN,
            "WARNING": EventLevel.WARN,
            "ERROR": EventLevel.ERROR,
        }
        console_level = level_map.get(console_level_str.upper(), EventLevel.INFO)

        # Create formatter for agent-actions specific events
        formatter = AgentActionsFormatter(show_timestamp=True, use_color=True)

        # Register console handler (user-facing)
        # Shows workflow/agent/batch events by default, all in verbose mode
        if verbose:
            categories = None  # Show all categories in verbose mode
        else:
            categories = {"workflow", "agent", "batch"}

        console_handler = ConsoleEventHandler(
            min_level=console_level,
            show_timestamp=True,
            formatter=formatter.format,
            categories=categories,
        )
        manager.register(console_handler)

        # Register JSON file handler for debug logs
        if output_dir:
            output_path = Path(output_dir)
            log_file = output_path / "target" / "events.json"
            json_handler = JSONFileHandler(
                file_path=log_file,
                min_level=EventLevel.DEBUG,
                buffer_size=5,
            )
            manager.register(json_handler)
        elif config.file_handler.enabled:
            # Use configured log file path
            log_file_path = cls._get_log_file_path()
            if log_file_path:
                json_handler = JSONFileHandler(
                    file_path=log_file_path,
                    min_level=EventLevel.DEBUG,
                    buffer_size=10,
                )
                manager.register(json_handler)

        # Register run results collector
        run_results = RunResultsCollector(
            output_dir=output_dir,
            workflow_name=workflow_name,
        )
        manager.register(run_results)
        cls._run_results_collector = run_results

    @classmethod
    def _setup_logging_bridge(cls) -> None:
        """
        Setup Python logging to route through events.

        Attaches LoggingBridgeHandler to the root agent_actions logger,
        converting all logging calls to events.
        """
        from agent_actions.logging.core.handlers import LoggingBridgeHandler

        # Get root logger for agent_actions
        root_logger = logging.getLogger(cls._root_logger_name)

        # Clear existing handlers
        root_logger.handlers.clear()

        # Set level to DEBUG so bridge receives everything
        # The event handlers will filter by level
        root_logger.setLevel(logging.DEBUG)

        # Add the bridge handler
        bridge = LoggingBridgeHandler(level=logging.DEBUG)
        root_logger.addHandler(bridge)

        # Prevent propagation to avoid duplicate messages
        root_logger.propagate = False

    @classmethod
    def _get_log_file_path(cls) -> Optional[Path]:
        """Determine the log file path."""
        if not cls._config:
            return None

        if cls._config.file_handler.path:
            return Path(cls._config.file_handler.path)

        # Try project root
        project_root = cls._get_project_root()
        if project_root:
            return project_root / "logs" / "events.json"

        # Fallback to home directory
        return Path.home() / ".agent-actions" / "logs" / "events.json"

    @classmethod
    def _get_project_root(cls) -> Optional[Path]:
        """Find the project root directory."""
        current = Path.cwd()
        for parent in [current] + list(current.parents):
            if (parent / "agent_actions.yml").exists():
                return parent
        return None

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        Get a logger with the given name.

        The logger's output will flow through the event system.

        Args:
            name: Logger name. Will be prefixed with 'agent_actions.' if needed.

        Returns:
            Configured logging.Logger instance.
        """
        if not cls._initialized:
            cls.initialize()

        # Ensure logger is under agent_actions namespace
        if not name.startswith(cls._root_logger_name):
            name = f"{cls._root_logger_name}.{name}"

        return logging.getLogger(name)

    @classmethod
    def set_level(cls, level: str, logger_name: Optional[str] = None) -> None:
        """Set log level for a logger."""
        if not cls._initialized:
            cls.initialize()

        if logger_name:
            if not logger_name.startswith(cls._root_logger_name):
                logger_name = f"{cls._root_logger_name}.{logger_name}"
            logger = logging.getLogger(logger_name)
        else:
            logger = logging.getLogger(cls._root_logger_name)

        logger.setLevel(getattr(logging, level.upper()))

    @classmethod
    def set_debug(cls, debug: bool = True) -> None:
        """Enable or disable debug logging globally."""
        level = "DEBUG" if debug else "INFO"
        cls.set_level(level)

    @classmethod
    def get_config(cls) -> Optional[LoggingConfig]:
        """Get the current logging configuration."""
        return cls._config

    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the factory has been initialized."""
        return cls._initialized

    @classmethod
    def reset(cls) -> None:
        """Reset the factory state (for testing)."""
        cls._initialized = False
        cls._config = None
        cls._event_manager = None
        cls._run_results_collector = None

        # Clear handlers from root logger
        root_logger = logging.getLogger(cls._root_logger_name)
        root_logger.handlers.clear()
        for f in root_logger.filters[:]:
            root_logger.removeFilter(f)

        # Reset event manager
        from agent_actions.logging.core import EventManager

        EventManager.reset()

    @classmethod
    def get_event_manager(cls) -> Optional["EventManager"]:
        """Get the current EventManager instance."""
        return cls._event_manager

    @classmethod
    def get_run_results_collector(cls) -> Optional["RunResultsCollector"]:
        """Get the RunResultsCollector instance."""
        return cls._run_results_collector

    @classmethod
    def set_context(cls, **kwargs) -> None:
        """Set shared context values for all events."""
        if cls._event_manager:
            cls._event_manager.set_context(**kwargs)

    @classmethod
    def flush(cls) -> None:
        """Flush all event handlers."""
        if cls._event_manager:
            cls._event_manager.flush()

    @classmethod
    def enable_context_debug(cls) -> "ContextDebugHandler":
        """
        Enable and return the context debug handler.

        This handler collects context-related events during workflow execution
        and provides a summary display for the --debug-context flag.

        Returns:
            The ContextDebugHandler instance

        Example:
            >>> handler = LoggerFactory.enable_context_debug()
            >>> # ... workflow execution ...
            >>> handler.display_summary()
        """
        if not cls._initialized:
            cls.initialize()

        from agent_actions.logging.core.handlers import ContextDebugHandler

        handler = ContextDebugHandler()

        if cls._event_manager:
            cls._event_manager.register(handler)

        return handler
