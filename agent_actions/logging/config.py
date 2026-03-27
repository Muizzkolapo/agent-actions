"""Logging configuration dataclasses."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


@dataclass
class FileHandlerSettings:
    """File handler configuration settings."""

    enabled: bool = True
    path: str | None = None
    level: LogLevel = "DEBUG"
    max_bytes: int = 10_485_760  # 10MB
    backup_count: int = 5
    format: Literal["human", "json"] = "human"


@dataclass
class LoggingConfig:
    """Central logging configuration."""

    default_level: LogLevel = "INFO"
    module_levels: dict[str, LogLevel] = field(default_factory=dict)
    include_timestamps: bool = True
    include_source_location: bool = False
    file_handler: FileHandlerSettings = field(default_factory=FileHandlerSettings)

    @classmethod
    def from_project_config(cls, config: dict) -> LoggingConfig:
        """Create LoggingConfig from a project configuration dictionary."""
        logging_config = config.get("logging", {})

        file_config = logging_config.get("file", {})
        file_settings = FileHandlerSettings(
            enabled=file_config.get("enabled", True),
            path=file_config.get("path"),
            level=cls._validate_log_level(file_config.get("level", "DEBUG"), "DEBUG"),
            max_bytes=file_config.get("max_bytes", 10_485_760),
            backup_count=file_config.get("backup_count", 5),
            format=file_config.get("format", "human"),
        )

        return cls(
            default_level=cls._validate_log_level(logging_config.get("level", "INFO"), "INFO"),
            module_levels=logging_config.get("module_levels", {}),
            include_timestamps=logging_config.get("include_timestamps", True),
            include_source_location=logging_config.get("include_source_location", False),
            file_handler=file_settings,
        )

    @staticmethod
    def _validate_log_level(value: str, default: str) -> LogLevel:
        """Validate and return a LogLevel, falling back to default."""
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper() if isinstance(value, str) else default
        return cast(LogLevel, upper if upper in valid else default)

    @classmethod
    def from_environment(cls) -> LoggingConfig:
        """Create LoggingConfig from AGENT_ACTIONS_* environment variables."""
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

        file_enabled = os.environ.get("AGENT_ACTIONS_NO_LOG_FILE", "0") != "1"

        file_path = os.environ.get("AGENT_ACTIONS_LOG_FILE") or None
        if not file_path:
            log_dir = os.environ.get("AGENT_ACTIONS_LOG_DIR")
            if log_dir:
                file_path = str(Path(log_dir) / "agent_actions.log")

        file_level = os.environ.get("AGENT_ACTIONS_FILE_LOG_LEVEL", "DEBUG").upper()
        if file_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            file_level = "DEBUG"

        file_settings = FileHandlerSettings(
            enabled=file_enabled,
            path=file_path,
            level=cast(LogLevel, file_level),
            format=cast(Literal["human", "json"], log_format),
        )

        return cls(
            default_level=cast(LogLevel, level),
            include_source_location=include_source,
            file_handler=file_settings,
        )
