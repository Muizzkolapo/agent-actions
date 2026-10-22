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

# The keys of agent_actions.yml's logging: block that a handler reads. Anything else
# under it is reported at boot rather than accepted silently.
PROJECT_LOGGING_KEYS: frozenset[str] = frozenset({"level", "module_levels", "file"})
PROJECT_LOGGING_FILE_KEYS: frozenset[str] = frozenset({"max_bytes", "backup_count"})


def _project_mapping(value: object, key: str) -> dict:
    """Return *value* as the mapping at *key* of ``agent_actions.yml``; report anything else."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    sys.stderr.write(
        f"agent_actions: ignoring {key}: expected a mapping, got {type(value).__name__}: {value!r}\n"
    )
    return {}


def _report_unread_keys(block: dict, read: frozenset[str], prefix: str) -> None:
    """Name each key under *prefix* that no handler reads, so it is not silently accepted."""
    for key in sorted(str(k) for k in block if str(k) not in read):
        sys.stderr.write(
            f"agent_actions: ignoring {prefix}.{key}: not read and configures nothing; "
            f"remove it (keys read under {prefix}: {', '.join(sorted(read))})\n"
        )


def _project_int(block: dict, key: str, default: int, minimum: int) -> int:
    """Read an integer from the ``logging.file`` block; report and use *default* otherwise."""
    raw = block.get(key)
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < minimum:
        sys.stderr.write(
            f"agent_actions: ignoring logging.file.{key}={raw!r}: must be an integer "
            f">= {minimum}; using {default}\n"
        )
        return default
    return int(raw)


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
        """Build from the ``logging:`` block of ``agent_actions.yml``; keys nothing reads are reported."""
        logging_config = _project_mapping(config.get("logging"), "logging")
        file_config = _project_mapping(logging_config.get("file"), "logging.file")
        _report_unread_keys(logging_config, PROJECT_LOGGING_KEYS, "logging")
        _report_unread_keys(file_config, PROJECT_LOGGING_FILE_KEYS, "logging.file")

        file_settings = FileHandlerSettings(
            max_bytes=_project_int(file_config, "max_bytes", DEFAULT_LOG_MAX_BYTES, 0),
            backup_count=_project_int(file_config, "backup_count", DEFAULT_LOG_RETAIN_RUNS, 1),
        )

        raw_module_levels = logging_config.get("module_levels", {})
        if not isinstance(raw_module_levels, dict):
            sys.stderr.write(
                "agent_actions: ignoring logging.module_levels "
                f"(expected dict, got {type(raw_module_levels).__name__}: "
                f"{raw_module_levels!r})\n"
            )
            raw_module_levels = {}

        raw_level = logging_config.get("level")
        level = cls.normalize_log_level(raw_level) if raw_level is not None else None
        if raw_level is not None and level is None:
            sys.stderr.write(
                f"agent_actions: ignoring logging.level={raw_level!r}: must be one of "
                f"{sorted(VALID_LOG_LEVELS)}; using INFO\n"
            )

        return cls(
            default_level=level or "INFO",
            module_levels=raw_module_levels,
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
    def from_environment(cls, base: LoggingConfig | None = None) -> LoggingConfig:
        """Overlay the AGENT_ACTIONS_* env vars on *base* (the defaults when None).

        An unset variable keeps the base value, so a project's ``logging:`` block
        passed as *base* is overridden only where the environment says so.
        ``module_levels`` has no env form.
        """
        base = base or cls()
        file_base = base.file_handler
        debug_mode = os.environ.get("AGENT_ACTIONS_DEBUG", "0") == "1"

        if debug_mode:
            level: LogLevel = "DEBUG"
            include_source = True
        else:
            level = cls._validate_log_level(
                os.environ.get("AGENT_ACTIONS_LOG_LEVEL", base.default_level), base.default_level
            )
            include_source = base.include_source_location

        log_format = os.environ.get("AGENT_ACTIONS_LOG_FORMAT", file_base.format).lower()
        if log_format not in ("human", "json"):
            log_format = file_base.format

        no_log_file = os.environ.get("AGENT_ACTIONS_NO_LOG_FILE")
        file_enabled = file_base.enabled if no_log_file is None else no_log_file != "1"

        file_path = os.environ.get("AGENT_ACTIONS_LOG_FILE") or None
        if not file_path:
            log_dir = os.environ.get("AGENT_ACTIONS_LOG_DIR")
            file_path = str(Path(log_dir) / "agent_actions.log") if log_dir else file_base.path

        file_level = cls._validate_log_level(
            os.environ.get("AGENT_ACTIONS_FILE_LOG_LEVEL", file_base.level), file_base.level
        )

        file_settings = FileHandlerSettings(
            enabled=file_enabled,
            path=file_path,
            level=file_level,
            max_bytes=_env_int("AGENT_ACTIONS_LOG_MAX_BYTES", file_base.max_bytes, 0),
            backup_count=_env_int("AGENT_ACTIONS_LOG_RETAIN_RUNS", file_base.backup_count, 1),
            format=cast(Literal["human", "json"], log_format),
        )

        return cls(
            default_level=level,
            module_levels=dict(base.module_levels),
            include_timestamps=base.include_timestamps,
            include_source_location=include_source,
            file_handler=file_settings,
        )
