"""Logging configuration dataclasses."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

VALID_LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

DEFAULT_LOG_MAX_BYTES = 52_428_800  # 50 MB
DEFAULT_LOG_RETAIN_RUNS = 5


def _env_int(name: str, default: int, minimum: int) -> int:
    """Read an integer env var; report and use *default* when it is not an int >= *minimum*."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = minimum - 1
    if value < minimum:
        sys.stderr.write(
            f"agent_actions: ignoring {name}={raw!r}: must be an integer >= {minimum}; "
            f"using {default}\n"
        )
        return default
    return value


@dataclass
class FileHandlerSettings:
    """File handler configuration settings."""

    enabled: bool = True
    path: str | None = None
    level: LogLevel = "DEBUG"
    # Per run file: past this many bytes, DEBUG rows are no longer written. 0 = no cap.
    max_bytes: int = DEFAULT_LOG_MAX_BYTES
    # Earlier runs kept beside the current one, as events.1.json ... events.N.json.
    backup_count: int = DEFAULT_LOG_RETAIN_RUNS
    format: Literal["human", "json"] = "human"


@dataclass
class LoggingConfig:
    """Central logging configuration."""

    default_level: LogLevel = "INFO"
    # Keys and values both validated at apply time by ``_apply_logger_levels``
    # — YAML can hand back non-string keys (numeric ids) and values.
    module_levels: dict[Any, Any] = field(default_factory=dict)
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
            max_bytes=file_config.get("max_bytes", DEFAULT_LOG_MAX_BYTES),
            backup_count=file_config.get("backup_count", DEFAULT_LOG_RETAIN_RUNS),
            format=file_config.get("format", "human"),
        )

        raw_module_levels = logging_config.get("module_levels", {})
        if not isinstance(raw_module_levels, dict):
            sys.stderr.write(
                "agent_actions: ignoring logging.module_levels "
                f"(expected dict, got {type(raw_module_levels).__name__}: "
                f"{raw_module_levels!r})\n"
            )
            raw_module_levels = {}

        return cls(
            default_level=cls._validate_log_level(logging_config.get("level", "INFO"), "INFO"),
            module_levels=raw_module_levels,
            include_timestamps=logging_config.get("include_timestamps", True),
            include_source_location=logging_config.get("include_source_location", False),
            file_handler=file_settings,
        )

    @staticmethod
    def normalize_log_level(value: object) -> LogLevel | None:
        """Return canonical LogLevel; None for non-string or unrecognized."""
        if not isinstance(value, str):
            return None
        upper = value.upper()
        if upper == "WARN":
            upper = "WARNING"
        if upper not in VALID_LOG_LEVELS:
            return None
        return cast(LogLevel, upper)

    @classmethod
    def _validate_log_level(cls, value: object, default: str) -> LogLevel:
        """Validate and return a LogLevel; fall back to default if invalid."""
        normalized = cls.normalize_log_level(value)
        return normalized if normalized is not None else cast(LogLevel, default)

    @classmethod
    def from_environment(cls) -> LoggingConfig:
        """Build LoggingConfig from AGENT_ACTIONS_* env vars; module_levels env wiring not supported."""
        debug_mode = os.environ.get("AGENT_ACTIONS_DEBUG", "0") == "1"

        if debug_mode:
            level: LogLevel = "DEBUG"
            include_source = True
        else:
            level = cls._validate_log_level(
                os.environ.get("AGENT_ACTIONS_LOG_LEVEL", "INFO"), "INFO"
            )
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

        file_level = cls._validate_log_level(
            os.environ.get("AGENT_ACTIONS_FILE_LOG_LEVEL", "DEBUG"), "DEBUG"
        )

        file_settings = FileHandlerSettings(
            enabled=file_enabled,
            path=file_path,
            level=file_level,
            max_bytes=_env_int("AGENT_ACTIONS_LOG_MAX_BYTES", DEFAULT_LOG_MAX_BYTES, 0),
            backup_count=_env_int("AGENT_ACTIONS_LOG_RETAIN_RUNS", DEFAULT_LOG_RETAIN_RUNS, 1),
            format=cast(Literal["human", "json"], log_format),
        )

        return cls(
            default_level=level,
            include_source_location=include_source,
            file_handler=file_settings,
        )
