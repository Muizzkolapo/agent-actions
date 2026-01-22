"""
Core event infrastructure for centralized logging.

This module provides a reusable event-based logging system inspired by dbt.
It has ZERO dependencies on agent_actions domain code, making it portable
to other projects.

Usage:
    from agent_actions.logging.core import EventManager, BaseEvent, fire_event

    # Register handlers
    manager = EventManager.get()
    manager.register(ConsoleEventHandler())

    # Fire events from anywhere
    fire_event(MyEvent(message="Something happened"))
"""

from agent_actions.logging.core.events import (
    BaseEvent,
    EventCategory,
    EventLevel,
    EventMeta,
)
from agent_actions.logging.core.manager import EventManager, fire_event, get_manager
from agent_actions.logging.core.protocols import (
    CategoryFilter,
    EventFilter,
    EventHandler,
    LevelFilter,
)
from agent_actions.logging.core.handlers import (
    ConsoleEventHandler,
    JSONFileHandler,
    StructuredLogHandler,
)

__all__ = [
    # Events
    "BaseEvent",
    "EventLevel",
    "EventCategory",
    "EventMeta",
    # Manager
    "EventManager",
    "fire_event",
    "get_manager",
    # Protocols
    "EventHandler",
    "EventFilter",
    "LevelFilter",
    "CategoryFilter",
    # Handlers
    "ConsoleEventHandler",
    "JSONFileHandler",
    "StructuredLogHandler",
]
