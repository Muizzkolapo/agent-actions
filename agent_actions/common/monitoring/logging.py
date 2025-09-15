"""Logging utilities for agent actions."""

import logging
from typing import Dict, Any, Optional


class LoggerFactory:
    """Factory for creating loggers."""

    @staticmethod
    def get_logger(name: str = __name__) -> logging.Logger:
        """Get a logger instance."""
        return logging.getLogger(name)


class LoggingContext:
    """Context for structured logging."""

    def __init__(self, logger: logging.Logger, context: Dict[str, Any]):
        self.logger = logger
        self.context = context

    def info(self, message: str, **kwargs):
        """Log info message with context."""
        self.logger.info(f"{message} | Context: {self.context} | Extra: {kwargs}")

    def error(self, message: str, **kwargs):
        """Log error message with context."""
        self.logger.error(f"{message} | Context: {self.context} | Extra: {kwargs}")

    def debug(self, message: str, **kwargs):
        """Log debug message with context."""
        self.logger.debug(f"{message} | Context: {self.context} | Extra: {kwargs}")


def get_logger() -> LoggingContext:
    """Get a structured logger."""
    logger = logging.getLogger(__name__)
    return LoggingContext(logger, {})


def log_where_clause_start(operation: str, scope: str, condition_count: int, item_count: int):
    """Log WHERE clause operation start."""
    logger = logging.getLogger(__name__)
    logger.debug(f"WHERE clause {operation} started: scope={scope}, conditions={condition_count}, items={item_count}")


def log_where_clause_success(operation: str, scope: str, duration_ms: float, condition_count: int, total_items: int, passed_items: int):
    """Log WHERE clause operation success."""
    logger = logging.getLogger(__name__)
    logger.info(f"WHERE clause {operation} success: scope={scope}, duration={duration_ms}ms, conditions={condition_count}, items={total_items}, passed={passed_items}")


def log_where_clause_error(operation: str, scope: str, duration_ms: float, condition_count: int, error: Exception, context: Dict[str, Any]):
    """Log WHERE clause operation error."""
    logger = logging.getLogger(__name__)
    logger.error(f"WHERE clause {operation} error: scope={scope}, duration={duration_ms}ms, conditions={condition_count}, error={error}, context={context}")


def log_security_violation(violation_type: str, severity: str, details: Dict[str, Any]):
    """Log security violation."""
    logger = logging.getLogger(__name__)
    logger.warning(f"Security violation: type={violation_type}, severity={severity}, details={details}")