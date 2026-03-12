"""Agent Actions logging infrastructure."""

from agent_actions.logging.config import LoggingConfig, LogLevel
from agent_actions.logging.factory import LoggerFactory
from agent_actions.logging.filters import RedactingFilter
from agent_actions.logging.formatters import JSONFormatter

# Event system exports
from agent_actions.logging.core import (
    BaseEvent,
    EventLevel,
    EventManager,
    fire_event,
    get_manager,
)

__all__ = [
    # Factory
    "LoggerFactory",
    # Configuration
    "LoggingConfig",
    "LogLevel",
    # Filters
    "RedactingFilter",
    # Formatters
    "JSONFormatter",
    # Event System
    "EventManager",
    "BaseEvent",
    "EventLevel",
    "fire_event",
    "get_manager",
]
