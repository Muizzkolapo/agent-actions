"""Agent Actions logging infrastructure.

This module provides structured logging with correlation IDs, consistent
formatting, and centralized configuration for the Agent Actions framework.

Example:
    >>> from agent_actions.logging import LoggerFactory, CorrelationContext
    >>> LoggerFactory.initialize()
    >>> logger = LoggerFactory.get_logger('my_module')
    >>> ctx = CorrelationContext.start_workflow('my-workflow')
    >>> logger.info('Starting processing')  # Includes correlation_id
"""

from agent_actions.logging.config import HandlerConfig, LoggingConfig, LogLevel
from agent_actions.logging.context import CorrelationContext, ExecutionContext
from agent_actions.logging.factory import LoggerFactory
from agent_actions.logging.filters import ContextInjectingFilter, RedactingFilter
from agent_actions.logging.formatters import HumanFormatter, JSONFormatter, SimpleFormatter

__all__ = [
    # Factory
    'LoggerFactory',
    # Configuration
    'LoggingConfig',
    'HandlerConfig',
    'LogLevel',
    # Context
    'CorrelationContext',
    'ExecutionContext',
    # Filters
    'ContextInjectingFilter',
    'RedactingFilter',
    # Formatters
    'JSONFormatter',
    'HumanFormatter',
    'SimpleFormatter',
]
