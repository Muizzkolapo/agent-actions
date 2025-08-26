"""
Modular structured logging system with correlation tracking and domain-specific extensions.

Architecture:
- StructuredLogger: General-purpose structured logging with JSON output
- LoggerFactory: Thread-safe factory for creating loggers and extensions  
- Domain Extensions: Specialized loggers for specific use cases
  - WhereClauseLogger: WHERE clause evaluation logging
  - CircuitBreakerLogger: Circuit breaker state logging
  - FeatureFlagLogger: Feature flag change logging

Usage Example:
    # Through DI container
    logger_factory = container.get(LoggerFactory)
    
    # General logging
    logger = logger_factory.create_logger(component="my_component")
    logger.info("Something happened", extra_data={"key": "value"})
    
    # Domain-specific logging
    where_logger = logger_factory.create_where_clause_logger()
    where_logger.log_evaluation(...)

This follows the Single Responsibility Principle by separating general logging
from domain-specific concerns.
"""
import json
import logging
import threading
from contextvars import ContextVar
from typing import Dict, Any, Optional
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
    """General structured logging context."""
    correlation_id: Optional[str] = None
    agent_type: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    operation: Optional[str] = None
    component: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class LogEntry:
    """General structured log entry."""
    timestamp: str
    level: str
    message: str
    context: LogContext
    error_details: Optional[Dict[str, Any]] = None
    performance_metrics: Optional[Dict[str, Any]] = None
    security_context: Optional[Dict[str, Any]] = None
    extra_data: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert context to dict
        data['context'] = self.context.to_dict()
        # Remove None values
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class WhereClauseLogEntry(LogEntry):
    """Specialized log entry for WHERE clause operations."""
    where_clause: Optional[str] = None
    scope: Optional[str] = None
    evaluation_time_ms: Optional[float] = None
    conditions_count: Optional[int] = None
    filtered_items: Optional[int] = None
    total_items: Optional[int] = None


class StructuredLogger:
    """
    General-purpose structured logger with correlation tracking and context management.
    Provides thread-safe, structured logging with JSON output.
    """
    
    def __init__(self, name: str = "agent_actions", level: str = "INFO", component: Optional[str] = None):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        self.component = component
        
        # Configure structured formatter if not already configured
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = StructuredFormatter()
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        self._local = threading.local()
    
    def _get_context(self, additional_context: Optional[Dict[str, Any]] = None) -> LogContext:
        """Get current logging context with optional additional data."""
        context = LogContext(
            correlation_id=correlation_id_var.get(),
            agent_type=agent_type_var.get(),
            user_id=user_id_var.get(),
            session_id=session_id_var.get(),
            component=self.component
        )
        
        # Merge additional context
        if additional_context:
            for key, value in additional_context.items():
                if hasattr(context, key) and value is not None:
                    setattr(context, key, value)
        
        return context
    
    def _create_log_entry(
        self,
        level: LogLevel,
        message: str,
        context_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> LogEntry:
        """Create a general structured log entry."""
        context = self._get_context(context_data)
        
        return LogEntry(
            timestamp=datetime.now(datetime.timezone.utc).isoformat(),
            level=level.value,
            message=message,
            context=context,
            **kwargs
        )
    
    def debug(self, message: str, context_data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log debug message."""
        entry = self._create_log_entry(LogLevel.DEBUG, message, context_data, **kwargs)
        self.logger.debug(json.dumps(entry.to_dict(), default=str))
    
    def info(self, message: str, context_data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log info message."""
        entry = self._create_log_entry(LogLevel.INFO, message, context_data, **kwargs)
        self.logger.info(json.dumps(entry.to_dict(), default=str))
    
    def warning(self, message: str, context_data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log warning message."""
        entry = self._create_log_entry(LogLevel.WARNING, message, context_data, **kwargs)
        self.logger.warning(json.dumps(entry.to_dict(), default=str))
    
    def error(self, message: str, context_data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log error message."""
        entry = self._create_log_entry(LogLevel.ERROR, message, context_data, **kwargs)
        self.logger.error(json.dumps(entry.to_dict(), default=str))
    
    def critical(self, message: str, context_data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log critical message."""
        entry = self._create_log_entry(LogLevel.CRITICAL, message, context_data, **kwargs)
        self.logger.critical(json.dumps(entry.to_dict(), default=str))
    
    def log_security_event(self, event_type: str, severity: str, details: Dict[str, Any]):
        """Log security-related events."""
        security_context = {
            "event_type": event_type,
            "severity": severity,
            "timestamp": datetime.now(datetime.timezone.utc).isoformat()
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
    
    def log_performance_warning(self, operation: str, duration_ms: float, threshold_ms: float, context_data: Optional[Dict[str, Any]] = None):
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


class WhereClauseLogger:
    """
    Domain-specific logger extension for WHERE clause operations.
    Builds on top of StructuredLogger to provide specialized logging methods.
    """
    
    def __init__(self, base_logger: StructuredLogger):
        self.logger = base_logger
    
    def _create_where_clause_entry(
        self,
        level: LogLevel,
        message: str,
        where_clause: str,
        scope: str,
        evaluation_time_ms: float,
        conditions_count: int,
        filtered_items: Optional[int] = None,
        total_items: Optional[int] = None,
        error_details: Optional[Dict[str, Any]] = None
    ) -> WhereClauseLogEntry:
        """Create a WHERE clause specific log entry."""
        context = self.logger._get_context()
        
        return WhereClauseLogEntry(
            timestamp=datetime.now(datetime.timezone.utc).isoformat(),
            level=level.value,
            message=message,
            context=context,
            where_clause=where_clause,
            scope=scope,
            evaluation_time_ms=evaluation_time_ms,
            conditions_count=conditions_count,
            filtered_items=filtered_items,
            total_items=total_items,
            error_details=error_details
        )
    
    def log_evaluation(
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
        
        entry = self._create_where_clause_entry(
            level,
            message,
            where_clause,
            scope,
            evaluation_time_ms,
            conditions_count,
            filtered_items,
            total_items,
            error_details
        )
        
        if success:
            self.logger.logger.info(json.dumps(entry.to_dict(), default=str))
        else:
            self.logger.logger.error(json.dumps(entry.to_dict(), default=str))
    
    def log_start(self, where_clause: str, scope: str, conditions_count: int, total_items: int):
        """Log the start of WHERE clause evaluation."""
        self.logger.info(
            f"Starting WHERE clause evaluation for {scope} scope",
            extra_data={
                "where_clause": where_clause,
                "scope": scope,
                "conditions_count": conditions_count,
                "total_items": total_items
            }
        )
    
    def log_success(
        self,
        where_clause: str,
        scope: str,
        evaluation_time_ms: float,
        conditions_count: int,
        filtered_items: int,
        total_items: int
    ):
        """Log successful WHERE clause evaluation."""
        self.log_evaluation(
            where_clause=where_clause,
            scope=scope,
            success=True,
            evaluation_time_ms=evaluation_time_ms,
            conditions_count=conditions_count,
            filtered_items=filtered_items,
            total_items=total_items
        )
    
    def log_error(
        self,
        where_clause: str,
        scope: str,
        evaluation_time_ms: float,
        conditions_count: int,
        error: Exception,
        context_data: Optional[Dict[str, Any]] = None
    ):
        """Log WHERE clause evaluation error."""
        error_details = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "where_clause_length": len(where_clause)
        }
        
        if context_data:
            error_details.update(context_data)
        
        self.log_evaluation(
            where_clause=where_clause,
            scope=scope,
            success=False,
            evaluation_time_ms=evaluation_time_ms,
            conditions_count=conditions_count,
            error_details=error_details
        )


class CircuitBreakerLogger:
    """
    Domain-specific logger extension for circuit breaker operations.
    """
    
    def __init__(self, base_logger: StructuredLogger):
        self.logger = base_logger
    
    def log_state_change(self, agent_type: str, state: str, failure_count: int, failure_threshold: int):
        """Log circuit breaker state changes."""
        self.logger.warning(
            f"Circuit breaker state changed to {state}",
            context_data={'agent_type': agent_type},
            error_details={
                "state": state,
                "failure_count": failure_count,
                "failure_threshold": failure_threshold
            }
        )


class FeatureFlagLogger:
    """
    Domain-specific logger extension for feature flag operations.
    """
    
    def __init__(self, base_logger: StructuredLogger):
        self.logger = base_logger
    
    def log_change(self, flag_name: str, old_value: bool, new_value: bool, agent_type: Optional[str] = None):
        """Log feature flag changes."""
        self.logger.info(
            f"Feature flag {flag_name} changed from {old_value} to {new_value}",
            context_data={'agent_type': agent_type} if agent_type else None,
            extra_data={
                "flag_name": flag_name,
                "old_value": old_value,
                "new_value": new_value
            }
        )


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
        del exc_type, exc_val, exc_tb  # Parameters required by context manager protocol
        correlation_id_var.set(self._previous_values['correlation_id'])
        agent_type_var.set(self._previous_values['agent_type'])
        user_id_var.set(self._previous_values['user_id'])
        session_id_var.set(self._previous_values['session_id'])


class LoggerFactory:
    """
    Thread-safe factory for creating StructuredLogger instances and extensions.
    Can be injected through DI container to eliminate global state.
    """
    
    def __init__(self):
        self._loggers: Dict[str, StructuredLogger] = {}
        self._lock = threading.Lock()
        self._default_config = {'name': 'agent_actions', 'level': 'INFO'}
    
    def set_default_config(self, name: str = "agent_actions", level: str = "INFO"):
        """Set default configuration for new logger instances."""
        with self._lock:
            self._default_config = {'name': name, 'level': level}
    
    def create_logger(self, name: Optional[str] = None, level: Optional[str] = None, component: Optional[str] = None) -> StructuredLogger:
        """Create or return cached logger instance with thread-safe singleton behavior."""
        final_name = name or self._default_config['name']
        final_level = level or self._default_config['level']
        logger_key = f"{final_name}:{final_level}:{component or 'default'}"
        
        # Check if logger already exists
        if logger_key in self._loggers:
            return self._loggers[logger_key]
        
        # Create new logger with double-checked locking
        with self._lock:
            if logger_key not in self._loggers:
                self._loggers[logger_key] = StructuredLogger(name=final_name, level=final_level, component=component)
            return self._loggers[logger_key]
    
    def create_where_clause_logger(self, name: Optional[str] = None, level: Optional[str] = None) -> WhereClauseLogger:
        """Create a WHERE clause logger extension."""
        base_logger = self.create_logger(name, level, component="where_clause")
        return WhereClauseLogger(base_logger)
    
    def create_circuit_breaker_logger(self, name: Optional[str] = None, level: Optional[str] = None) -> CircuitBreakerLogger:
        """Create a circuit breaker logger extension."""
        base_logger = self.create_logger(name, level, component="circuit_breaker")
        return CircuitBreakerLogger(base_logger)
    
    def create_feature_flag_logger(self, name: Optional[str] = None, level: Optional[str] = None) -> FeatureFlagLogger:
        """Create a feature flag logger extension."""
        base_logger = self.create_logger(name, level, component="feature_flags")
        return FeatureFlagLogger(base_logger)
    
    def get_default_logger(self) -> StructuredLogger:
        """Get the default logger instance."""
        return self.create_logger()
    
    def clear_cache(self):
        """Clear cached logger instances. Useful for testing."""
        with self._lock:
            self._loggers.clear()


# Note: Global logger functions removed for production readiness
# Use LoggerFactory injection through DI container instead


# Convenience functions - now use domain-specific loggers
def log_where_clause_start(where_clause_logger: WhereClauseLogger, where_clause: str, scope: str, conditions_count: int, total_items: int):
    """Log the start of WHERE clause evaluation."""
    where_clause_logger.log_start(where_clause, scope, conditions_count, total_items)


def log_where_clause_success(
    where_clause_logger: WhereClauseLogger,
    where_clause: str,
    scope: str,
    evaluation_time_ms: float,
    conditions_count: int,
    filtered_items: int,
    total_items: int
):
    """Log successful WHERE clause evaluation."""
    where_clause_logger.log_success(
        where_clause=where_clause,
        scope=scope,
        evaluation_time_ms=evaluation_time_ms,
        conditions_count=conditions_count,
        filtered_items=filtered_items,
        total_items=total_items
    )


def log_where_clause_error(
    where_clause_logger: WhereClauseLogger,
    where_clause: str,
    scope: str,
    evaluation_time_ms: float,
    conditions_count: int,
    error: Exception,
    context_data: Optional[Dict[str, Any]] = None
):
    """Log WHERE clause evaluation error."""
    where_clause_logger.log_error(
        where_clause=where_clause,
        scope=scope,
        evaluation_time_ms=evaluation_time_ms,
        conditions_count=conditions_count,
        error=error,
        context_data=context_data
    )


def log_security_violation(logger: StructuredLogger, violation_type: str, severity: str, details: Dict[str, Any]):
    """Log security violations."""
    logger.log_security_event(violation_type, severity, details)


def log_performance_issue(logger: StructuredLogger, operation: str, duration_ms: float, threshold_ms: float, **context):
    """Log performance issues."""
    logger.log_performance_warning(operation, duration_ms, threshold_ms, context)