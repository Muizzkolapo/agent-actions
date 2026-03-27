"""Typed dictionaries for DI configuration boundaries."""

from typing import TypedDict


class LoggingConfig(TypedDict):
    """Logging settings within a DI configuration profile."""

    level: str
    enable_console: bool


class ProcessorsConfig(TypedDict):
    """Processor settings within a DI configuration profile."""

    cache_enabled: bool
    parallel_processing: bool


class ServicesConfig(TypedDict):
    """Service settings within a DI configuration profile."""

    batch_size: int
    timeout: int


class DIConfig(TypedDict):
    """Top-level DI configuration profile shape."""

    environment: str
    logging: LoggingConfig
    processors: ProcessorsConfig
    services: ServicesConfig
