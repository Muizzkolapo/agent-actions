"""Logging configuration dataclasses."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Literal, Optional

LogLevel = Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']


@dataclass
class HandlerConfig:
    """Configuration for a single log handler."""

    type: Literal['console', 'file', 'json']
    level: LogLevel = 'INFO'
    format: Literal['human', 'json'] = 'human'
    file_path: Optional[Path] = None
    max_bytes: int = 10_000_000  # 10MB
    backup_count: int = 5


@dataclass
class LoggingConfig:
    """Central logging configuration."""

    default_level: LogLevel = 'INFO'
    handlers: List[HandlerConfig] = field(default_factory=list)
    module_levels: Dict[str, LogLevel] = field(default_factory=dict)
    include_timestamps: bool = True
    include_source_location: bool = True
    redact_patterns: List[str] = field(
        default_factory=lambda: [
            r'api[_-]?key',
            r'secret',
            r'token',
            r'password',
            r'credential',
        ]
    )

    @classmethod
    def from_project_config(cls, config: dict) -> LoggingConfig:
        """Create LoggingConfig from project configuration.

        Args:
            config: Project configuration dictionary with optional 'logging' section.

        Returns:
            LoggingConfig instance with values from config or defaults.
        """
        logging_config = config.get('logging', {})

        handlers = []
        for handler_dict in logging_config.get('handlers', []):
            file_path = handler_dict.get('file_path')
            handlers.append(
                HandlerConfig(
                    type=handler_dict.get('type', 'console'),
                    level=handler_dict.get('level', 'INFO'),
                    format=handler_dict.get('format', 'human'),
                    file_path=Path(file_path) if file_path else None,
                    max_bytes=handler_dict.get('max_bytes', 10_000_000),
                    backup_count=handler_dict.get('backup_count', 5),
                )
            )

        return cls(
            default_level=logging_config.get('level', 'INFO'),
            handlers=handlers,
            module_levels=logging_config.get('module_levels', {}),
            include_timestamps=logging_config.get('include_timestamps', True),
            include_source_location=logging_config.get('include_source_location', True),
            redact_patterns=logging_config.get(
                'redact_patterns',
                [
                    r'api[_-]?key',
                    r'secret',
                    r'token',
                    r'password',
                    r'credential',
                ],
            ),
        )

    @classmethod
    def from_environment(cls) -> LoggingConfig:
        """Create LoggingConfig from environment variables.

        Supported environment variables:
            AGENT_ACTIONS_LOG_LEVEL: Default log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            AGENT_ACTIONS_LOG_FORMAT: Output format ('human' or 'json')

        Returns:
            LoggingConfig instance with values from environment or defaults.
        """
        level = os.environ.get('AGENT_ACTIONS_LOG_LEVEL', 'INFO').upper()
        if level not in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
            level = 'INFO'

        log_format = os.environ.get('AGENT_ACTIONS_LOG_FORMAT', 'human').lower()
        if log_format not in ('human', 'json'):
            log_format = 'human'

        handlers = [
            HandlerConfig(
                type='console',
                level=level,
                format=log_format,
            )
        ]

        return cls(
            default_level=level,
            handlers=handlers,
        )
