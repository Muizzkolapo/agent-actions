"""
Production-grade structured logging for WHERE clause filtering.
Implements structured logging with correlation IDs and context.
"""
import json
import logging
import threading
import time
from contextvars import ContextVar
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
import uuid

# Context variables for request correlation
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)
agent_type_var: ContextVar[Optional[str]] = ContextVar('agent_type', default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar('user_id', default=None)
session_id_var: ContextVar[Optional[str]] = ContextVar('session_id', default=None)


class LogLevel(Enum):
    """Structured log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogContext:
    """Structured logging context."""
    correlation_id: Optional[str] = None
    agent_type: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    operation: Optional[str] = None
    component: str = "where_clause"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class WhereClauseLogEntry:
    """Structured log entry for WHERE clause operations."""
    timestamp: str
    level: str
    message: str
    context: LogContext
    where_clause: Optional[str] = None
    scope: Optional[str] = None
    evaluation_time_ms: Optional[float] = None
    conditions_count: Optional[int] = None
    filtered_items: Optional[int] = None
    total_items: Optional[int] = None
    error_type: Optional[str] = None
    error_details: Optional[Dict[str, Any]] = None
    performance_metrics: Optional[Dict[str, Any]] = None
    security_context: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert context to dict
        data['context'] = self.context.to_dict()
        # Remove None values
        return {k: v for k, v in data.items() if v is not None}


class StructuredLogger:
    """
    Production-grade structured logger for WHERE clause operations.
    Provides correlation tracking, performance monitoring, and security logging.
    """
    
    def __init__(self, name: str = "where_clause", level: str = "INFO"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        
        # Configure structured formatter if not already configured
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = StructuredFormatter()
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        self._local = threading.local()
    
    def _get_context(self) -> LogContext:
        """Get current logging context."""
        return LogContext(
            correlation_id=correlation_id_var.get(),
            agent_type=agent_type_var.get(),
            user_id=user_id_var.get(),
            session_id=session_id_var.get()
        )
    
    def _create_log_entry(
        self,
        level: LogLevel,
        message: str,
        **kwargs
    ) -> WhereClauseLogEntry:
        """Create a structured log entry."""
        context = self._get_context()
        
        # Merge additional context
        if 'context' in kwargs:
            additional_context = kwargs.pop('context')
            if isinstance(additional_context, dict):
                for key, value in additional_context.items():
                    if hasattr(context, key) and value is not None:
                        setattr(context, key, value)
        
        return WhereClauseLogEntry(
            timestamp=datetime.utcnow().isoformat() + "Z",
            level=level.value,
            message=message,
            context=context,
            **kwargs
        )
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        entry = self._create_log_entry(LogLevel.DEBUG, message, **kwargs)
        self.logger.debug(json.dumps(entry.to_dict(), default=str))
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        entry = self._create_log_entry(LogLevel.INFO, message, **kwargs)
        self.logger.info(json.dumps(entry.to_dict(), default=str))
    
    def warning(self, message: str, **kwargs):
        """Log warning message."""
        entry = self._create_log_entry(LogLevel.WARNING, message, **kwargs)
        self.logger.warning(json.dumps(entry.to_dict(), default=str))
    
    def error(self, message: str, **kwargs):
        """Log error message."""
        entry = self._create_log_entry(LogLevel.ERROR, message, **kwargs)
        self.logger.error(json.dumps(entry.to_dict(), default=str))
    
    def critical(self, message: str, **kwargs):
        """Log critical message."""
        entry = self._create_log_entry(LogLevel.CRITICAL, message, **kwargs)
        self.logger.critical(json.dumps(entry.to_dict(), default=str))
    
    def log_where_clause_evaluation(
        self,
        where_clause: str,
        scope: str,
        success: bool,
        evaluation_time_ms: float,
        conditions_count: int,
        filtered_items: Optional[int] = None,
        total_items: Optional[int] = None,
        error_details: Optional[Dict[str, Any]] = None
    ):
        """Log WHERE clause evaluation with detailed context."""
        if success:
            message = f"WHERE clause evaluation successful for {scope} scope"
            level = LogLevel.INFO
        else:
            message = f"WHERE clause evaluation failed for {scope} scope"
            level = LogLevel.ERROR
        
        entry = self._create_log_entry(
            level,
            message,
            where_clause=where_clause,
            scope=scope,
            evaluation_time_ms=evaluation_time_ms,
            conditions_count=conditions_count,
            filtered_items=filtered_items,
            total_items=total_items,
            error_details=error_details
        )
        
        if success:
            self.logger.info(json.dumps(entry.to_dict(), default=str))
        else:
            self.logger.error(json.dumps(entry.to_dict(), default=str))
    
    def log_security_event(
        self,
        event_type: str,
        severity: str,
        details: Dict[str, Any]
    ):
        """Log security-related events."""
        security_context = {
            "event_type": event_type,
            "severity": severity,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
        
        level = LogLevel.WARNING if severity == "medium" else LogLevel.ERROR
        
        entry = self._create_log_entry(
            level,
            f"Security event: {event_type}",
            security_context=security_context,
            error_details=details
        )
        
        if level == LogLevel.WARNING:
            self.logger.warning(json.dumps(entry.to_dict(), default=str))
        else:
            self.logger.error(json.dumps(entry.to_dict(), default=str))
    
    def log_performance_warning(
        self,
        operation: str,
        duration_ms: float,
        threshold_ms: float,
        context_data: Optional[Dict[str, Any]] = None
    ):
        """Log performance warnings."""
        performance_metrics = {
            "operation": operation,
            "duration_ms": duration_ms,
            "threshold_ms": threshold_ms,
            "ratio": duration_ms / threshold_ms
        }
        
        if context_data:
            performance_metrics.update(context_data)
        
        entry = self._create_log_entry(
            LogLevel.WARNING,
            f"Performance threshold exceeded for {operation}",
            performance_metrics=performance_metrics
        )
        
        self.logger.warning(json.dumps(entry.to_dict(), default=str))
    
    def log_circuit_breaker_event(
        self,
        agent_type: str,
        state: str,
        failure_count: int,
        failure_threshold: int
    ):
        """Log circuit breaker state changes."""
        entry = self._create_log_entry(
            LogLevel.WARNING,
            f"Circuit breaker state changed to {state}",
            context={'agent_type': agent_type},
            error_details={
                "state": state,
                "failure_count": failure_count,
                "failure_threshold": failure_threshold
            }
        )
        
        self.logger.warning(json.dumps(entry.to_dict(), default=str))
    
    def log_feature_flag_change(
        self,
        flag_name: str,
        old_value: bool,
        new_value: bool,
        agent_type: Optional[str] = None
    ):
        """Log feature flag changes."""
        entry = self._create_log_entry(
            LogLevel.INFO,
            f"Feature flag {flag_name} changed from {old_value} to {new_value}",
            context={'agent_type': agent_type} if agent_type else None,
            error_details={
                "flag_name": flag_name,
                "old_value": old_value,
                "new_value": new_value
            }
        )
        
        self.logger.info(json.dumps(entry.to_dict(), default=str))


class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured logging."""
    
    def format(self, record):
        # If the message is already JSON, use it as-is
        try:
            json.loads(record.getMessage())
            return record.getMessage()
        except (json.JSONDecodeError, ValueError):
            # Fall back to standard formatting
            return super().format(record)


class LoggingContext:
    """Context manager for setting logging context."""
    
    def __init__(
        self,
        correlation_id: Optional[str] = None,
        agent_type: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        auto_generate_correlation_id: bool = True
    ):
        self.correlation_id = correlation_id or (str(uuid.uuid4()) if auto_generate_correlation_id else None)
        self.agent_type = agent_type
        self.user_id = user_id
        self.session_id = session_id
        
        # Store previous values for restoration
        self._previous_values = {}
    
    def __enter__(self):
        # Store previous values
        self._previous_values = {
            'correlation_id': correlation_id_var.get(),
            'agent_type': agent_type_var.get(),
            'user_id': user_id_var.get(),
            'session_id': session_id_var.get()
        }
        
        # Set new values
        if self.correlation_id is not None:
            correlation_id_var.set(self.correlation_id)
        if self.agent_type is not None:
            agent_type_var.set(self.agent_type)
        if self.user_id is not None:
            user_id_var.set(self.user_id)
        if self.session_id is not None:
            session_id_var.set(self.session_id)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore previous values
        correlation_id_var.set(self._previous_values['correlation_id'])
        agent_type_var.set(self._previous_values['agent_type'])
        user_id_var.set(self._previous_values['user_id'])
        session_id_var.set(self._previous_values['session_id'])


# Global logger instance
_structured_logger: Optional[StructuredLogger] = None
_logger_lock = threading.Lock()


def get_logger() -> StructuredLogger:
    """Get or create the global structured logger."""
    global _structured_logger
    
    if _structured_logger is None:
        with _logger_lock:
            if _structured_logger is None:
                _structured_logger = StructuredLogger()
    
    return _structured_logger


def init_logging(name: str = "where_clause", level: str = "INFO") -> StructuredLogger:
    """Initialize the global structured logger."""
    global _structured_logger
    
    with _logger_lock:
        _structured_logger = StructuredLogger(name=name, level=level)
    
    return _structured_logger


# Convenience functions
def log_where_clause_start(where_clause: str, scope: str, conditions_count: int, total_items: int):
    """Log the start of WHERE clause evaluation."""
    logger = get_logger()
    logger.info(
        f"Starting WHERE clause evaluation for {scope} scope",
        where_clause=where_clause,
        scope=scope,
        conditions_count=conditions_count,
        total_items=total_items
    )


def log_where_clause_success(
    where_clause: str,
    scope: str,
    evaluation_time_ms: float,
    conditions_count: int,
    filtered_items: int,
    total_items: int
):
    """Log successful WHERE clause evaluation."""
    logger = get_logger()
    logger.log_where_clause_evaluation(
        where_clause=where_clause,
        scope=scope,
        success=True,
        evaluation_time_ms=evaluation_time_ms,
        conditions_count=conditions_count,
        filtered_items=filtered_items,
        total_items=total_items
    )


def log_where_clause_error(
    where_clause: str,
    scope: str,
    evaluation_time_ms: float,
    conditions_count: int,
    error: Exception,
    context_data: Optional[Dict[str, Any]] = None
):
    """Log WHERE clause evaluation error."""
    logger = get_logger()
    
    error_details = {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "where_clause_length": len(where_clause)
    }
    
    if context_data:
        error_details.update(context_data)
    
    logger.log_where_clause_evaluation(
        where_clause=where_clause,
        scope=scope,
        success=False,
        evaluation_time_ms=evaluation_time_ms,
        conditions_count=conditions_count,
        error_details=error_details
    )


def log_security_violation(violation_type: str, severity: str, details: Dict[str, Any]):
    """Log security violations."""
    logger = get_logger()
    logger.log_security_event(violation_type, severity, details)


def log_performance_issue(operation: str, duration_ms: float, threshold_ms: float, **context):
    """Log performance issues."""
    logger = get_logger()
    logger.log_performance_warning(operation, duration_ms, threshold_ms, context)