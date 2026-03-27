"""Core event infrastructure for centralized logging."""

from agent_actions.logging.core.events import (
    BaseEvent,
    EventCategory,
    EventLevel,
    EventMeta,
)
from agent_actions.logging.core.handlers import (
    ConsoleEventHandler,
    ContextDebugHandler,
    JSONFileHandler,
)
from agent_actions.logging.core.manager import EventManager, fire_event, get_manager
from agent_actions.logging.core.protocols import (
    CategoryFilter,
    EventFilter,
    EventHandler,
    LevelFilter,
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
    "ContextDebugHandler",
]
