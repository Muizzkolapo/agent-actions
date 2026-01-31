"""
Core event handlers for the centralized logging system.

These handlers process events and output them to various destinations.
They have no dependencies on agent_actions domain code.
"""

from agent_actions.logging.core.handlers.console import ConsoleEventHandler
from agent_actions.logging.core.handlers.json_file import JSONFileHandler
from agent_actions.logging.core.handlers.structured import StructuredLogHandler
from agent_actions.logging.core.handlers.bridge import (
    LoggingBridgeHandler,
    LogEvent,
    DebugEvent,
    SystemEvent,
)
from agent_actions.logging.core.handlers.context_debug import ContextDebugHandler

__all__ = [
    "ConsoleEventHandler",
    "JSONFileHandler",
    "StructuredLogHandler",
    "LoggingBridgeHandler",
    "LogEvent",
    "DebugEvent",
    "SystemEvent",
    "ContextDebugHandler",
]
