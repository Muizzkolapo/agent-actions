"""Logger factory for centralized logging configuration."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from agent_actions.logging.config import LoggingConfig

if TYPE_CHECKING:
    from agent_actions.logging.core import EventManager
    from agent_actions.logging.core.handlers import ContextDebugHandler
    from agent_actions.logging.events.handlers import RunResultsCollector


class LoggerFactory:
    """Centralized logging factory routing all output through EventManager."""

    _initialized: bool = False
    _config: LoggingConfig | None = None
    _root_logger_name: str = "agent_actions"
    _event_manager: EventManager | None = None
    _run_results_collector: RunResultsCollector | None = None

    @classmethod
    def initialize(
        cls,
        config: LoggingConfig | None = None,
        output_dir: str | Path | None = None,
        workflow_name: str = "",
        invocation_id: str | None = None,
        verbose: bool = False,
        quiet: bool = False,
        force: bool = False,
    ) -> EventManager:
        """Initialize the unified logging system and return the EventManager."""
        if cls._initialized and not force:
            assert cls._event_manager is not None, (
                "LoggerFactory._initialized is True but _event_manager is None"
            )
            return cls._event_manager

        cls._config = config or LoggingConfig.from_environment()

        if verbose or cls._config.default_level == "DEBUG":
            console_level_str = "DEBUG"
        elif quiet:
            console_level_str = "WARN"
        else:
            console_level_str = cls._config.default_level

        from agent_actions.logging.core import (
            EventManager,
        )

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

        cls._setup_logging_bridge()

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

        if not invocation_id:
            invocation_id = str(uuid.uuid4())[:8]

        manager.set_context(
            invocation_id=invocation_id,
            workflow_name=workflow_name,
        )

        level_map = {
            "DEBUG": EventLevel.DEBUG,
            "INFO": EventLevel.INFO,
            "WARN": EventLevel.WARN,
            "WARNING": EventLevel.WARN,
            "ERROR": EventLevel.ERROR,
        }
        console_level = level_map.get(console_level_str.upper(), EventLevel.INFO)

        formatter = AgentActionsFormatter(show_timestamp=True, use_color=True)

        if verbose:
            categories = None
        else:
            categories = {"workflow", "agent", "batch"}

        console_handler = ConsoleEventHandler(
            min_level=console_level,
            show_timestamp=True,
            formatter=formatter.format,
            categories=categories,
        )
        manager.register(console_handler)

        if output_dir:
            output_path = Path(output_dir)
            log_file = output_path / "target" / "events.json"
            json_handler = JSONFileHandler(
                file_path=log_file,
                min_level=EventLevel.DEBUG,
                buffer_size=5,
            )
            manager.register(json_handler)

            errors_file = output_path / "target" / "errors.json"
            errors_handler = JSONFileHandler(
                file_path=errors_file,
                min_level=EventLevel.ERROR,
                buffer_size=1,
            )
            manager.register(errors_handler)
        elif config.file_handler.enabled:
            log_file_path = cls._get_log_file_path()
            if log_file_path:
                json_handler = JSONFileHandler(
                    file_path=log_file_path,
                    min_level=EventLevel.DEBUG,
                    buffer_size=10,
                )
                manager.register(json_handler)

        run_results = RunResultsCollector(
            output_dir=output_dir,
            workflow_name=workflow_name,
        )
        manager.register(run_results)
        cls._run_results_collector = run_results

    @classmethod
    def _setup_logging_bridge(cls) -> None:
        """Attach LoggingBridgeHandler to the root agent_actions logger."""
        from agent_actions.logging.core.handlers import LoggingBridgeHandler

        root_logger = logging.getLogger(cls._root_logger_name)

        root_logger.handlers.clear()

        # Event handlers will filter by level
        root_logger.setLevel(logging.DEBUG)

        bridge = LoggingBridgeHandler(level=logging.DEBUG)
        root_logger.addHandler(bridge)

        root_logger.propagate = False

    @classmethod
    def _get_log_file_path(cls) -> Path | None:
        """Determine the log file path."""
        if not cls._config:
            return None

        if cls._config.file_handler.path:
            return Path(cls._config.file_handler.path)

        project_root = cls._get_project_root()
        if project_root:
            return project_root / "logs" / "events.json"

        return Path.home() / ".agent-actions" / "logs" / "events.json"

    @classmethod
    def _get_project_root(cls) -> Path | None:
        """Find the project root directory.

        Best-effort fallback: uses Path.cwd() as search start.
        Primary callers should prefer passing explicit output_dir to initialize().
        """
        current = Path.cwd()
        for parent in [current] + list(current.parents):
            if (parent / "agent_actions.yml").exists():
                return parent
        return None

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a logger under the agent_actions namespace."""
        if not cls._initialized:
            cls.initialize()

        if not name.startswith(cls._root_logger_name):
            name = f"{cls._root_logger_name}.{name}"

        return logging.getLogger(name)

    @classmethod
    def set_level(cls, level: str, logger_name: str | None = None) -> None:
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
    def get_config(cls) -> LoggingConfig | None:
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

        root_logger = logging.getLogger(cls._root_logger_name)
        root_logger.handlers.clear()
        for f in root_logger.filters[:]:
            root_logger.removeFilter(f)

        from agent_actions.logging.core import EventManager

        EventManager.reset()

    @classmethod
    def get_event_manager(cls) -> EventManager | None:
        """Get the current EventManager instance."""
        return cls._event_manager

    @classmethod
    def get_run_results_collector(cls) -> RunResultsCollector | None:
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
    def enable_context_debug(cls) -> ContextDebugHandler:
        """Enable and return the context debug handler for --debug-context."""
        if not cls._initialized:
            cls.initialize()

        from agent_actions.logging.core.handlers import ContextDebugHandler

        handler = ContextDebugHandler()

        if cls._event_manager:
            cls._event_manager.register(handler)

        return handler
