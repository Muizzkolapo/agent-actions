"""Logging configuration dataclasses."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


@dataclass
class HandlerConfig:
    """Configuration for a single log handler."""

    type: Literal["console", "file", "json"]
    level: LogLevel = "INFO"
    format: Literal["human", "json"] = "human"
    file_path: Optional[Path] = None
    max_bytes: int = 10_000_000  # 10MB
    backup_count: int = 5


@dataclass
class FileHandlerSettings:
    """File handler configuration settings."""

    enabled: bool = True
    path: Optional[str] = None
    level: LogLevel = "DEBUG"
    max_bytes: int = 10_485_760  # 10MB
    backup_count: int = 5
    format: Literal["human", "json"] = "human"


@dataclass
class LoggingConfig:
    """Central logging configuration."""

    default_level: LogLevel = "INFO"
    handlers: List[HandlerConfig] = field(default_factory=list)
    module_levels: Dict[str, LogLevel] = field(default_factory=dict)
    include_timestamps: bool = True
    include_source_location: bool = False
    redact_patterns: List[str] = field(
        default_factory=lambda: [
            r"api[_-]?key",
            r"secret",
            r"token",
            r"password",
            r"credential",
        ]
    )
    file_handler: FileHandlerSettings = field(default_factory=FileHandlerSettings)

    # Legacy properties for backward compatibility
    @property
    def file_handler_enabled(self) -> bool:
        """Legacy property for backward compatibility."""
        return self.file_handler.enabled

    @property
    def log_file_path(self) -> Optional[str]:
        """Legacy property for backward compatibility."""
        return self.file_handler.path

    @property
    def file_log_level(self) -> LogLevel:
        """Legacy property for backward compatibility."""
        return self.file_handler.level

    @property
    def file_max_bytes(self) -> int:
        """Legacy property for backward compatibility."""
        return self.file_handler.max_bytes

    @property
    def file_backup_count(self) -> int:
        """Legacy property for backward compatibility."""
        return self.file_handler.backup_count

    @property
    def file_format(self) -> Literal["human", "json"]:
        """Legacy property for backward compatibility."""
        return self.file_handler.format

    @classmethod
    def from_project_config(cls, config: dict) -> LoggingConfig:
        """Create LoggingConfig from project configuration.

        Args:
            config: Project configuration dictionary with optional 'logging' section.

        Returns:
            LoggingConfig instance with values from config or defaults.
        """
        logging_config = config.get("logging", {})

        handlers = []
        for handler_dict in logging_config.get("handlers", []):
            file_path = handler_dict.get("file_path")
            handlers.append(
                HandlerConfig(
                    type=handler_dict.get("type", "console"),
                    level=handler_dict.get("level", "INFO"),
                    format=handler_dict.get("format", "human"),
                    file_path=Path(file_path) if file_path else None,
                    max_bytes=handler_dict.get("max_bytes", 10_000_000),
                    backup_count=handler_dict.get("backup_count", 5),
                )
            )

        # Parse file handler configuration from YAML
        file_config = logging_config.get("file", {})
        file_settings = FileHandlerSettings(
            enabled=file_config.get("enabled", True),
            path=file_config.get("path"),
            level=file_config.get("level", "DEBUG"),
            max_bytes=file_config.get("max_bytes", 10_485_760),
            backup_count=file_config.get("backup_count", 5),
            format=file_config.get("format", "human"),
        )

        return cls(
            default_level=logging_config.get("level", "INFO"),
            handlers=handlers,
            module_levels=logging_config.get("module_levels", {}),
            include_timestamps=logging_config.get("include_timestamps", True),
            include_source_location=logging_config.get("include_source_location", True),
            redact_patterns=logging_config.get(
                "redact_patterns",
                [
                    r"api[_-]?key",
                    r"secret",
                    r"token",
                    r"password",
                    r"credential",
                ],
            ),
            file_handler=file_settings,
        )

    @classmethod
    def from_environment(cls) -> LoggingConfig:
        """Create LoggingConfig from environment variables.

        Supported environment variables:
            AGENT_ACTIONS_DEBUG: Set to '1' to enable debug mode (DEBUG level + source location)
            AGENT_ACTIONS_LOG_LEVEL: Default log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            AGENT_ACTIONS_LOG_FORMAT: Output format ('human' or 'json')
            AGENT_ACTIONS_NO_LOG_FILE: Set to '1' to disable file logging
            AGENT_ACTIONS_LOG_FILE: Custom log file path (absolute or relative)
            AGENT_ACTIONS_LOG_DIR: Custom log directory (will use 'agent_actions.log' as filename)
            AGENT_ACTIONS_FILE_LOG_LEVEL: File log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

        Returns:
            LoggingConfig instance with values from environment or defaults.
        """
        # Check for debug mode first (overrides other settings)
        debug_mode = os.environ.get("AGENT_ACTIONS_DEBUG", "0") == "1"

        if debug_mode:
            level = "DEBUG"
            include_source = True
        else:
            level = os.environ.get("AGENT_ACTIONS_LOG_LEVEL", "INFO").upper()
            if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                level = "INFO"
            include_source = False

        log_format = os.environ.get("AGENT_ACTIONS_LOG_FORMAT", "human").lower()
        if log_format not in ("human", "json"):
            log_format = "human"

        handlers = [
            HandlerConfig(
                type="console",
                level=level,
                format=log_format,
            )
        ]

        # File handler configuration from environment
        file_enabled = os.environ.get("AGENT_ACTIONS_NO_LOG_FILE", "0") != "1"

        file_path = os.environ.get("AGENT_ACTIONS_LOG_FILE") or None
        if not file_path:
            log_dir = os.environ.get("AGENT_ACTIONS_LOG_DIR")
            if log_dir:
                file_path = str(Path(log_dir) / "agent_actions.log")

        file_level = os.environ.get("AGENT_ACTIONS_FILE_LOG_LEVEL", "DEBUG").upper()
        if file_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            file_level = "DEBUG"

        file_settings = FileHandlerSettings(enabled=file_enabled, path=file_path, level=file_level)

        return cls(
            default_level=level,
            handlers=handlers,
            include_source_location=include_source,
            file_handler=file_settings,
        )
