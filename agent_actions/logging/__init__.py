"""
Agent Actions logging infrastructure.

This module provides two logging approaches:

1. Traditional Python logging (LoggerFactory):
   - Standard logging with formatters and filters
   - Good for debug output and file logging

2. Event-based logging (EventManager, fire_event):
   - dbt-style centralized event system
   - Typed events with structured data
   - Clean console output with run_results.json artifact

Usage:
    # Traditional logging
    from agent_actions.logging import LoggerFactory
    logger = LoggerFactory.get_logger('my_module')
    logger.info('Hello world')

    # Event-based logging
    from agent_actions.logging import fire_event
    from agent_actions.logging.events import WorkflowStartEvent
    fire_event(WorkflowStartEvent(workflow_name="my_workflow", agent_count=5))
"""

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
