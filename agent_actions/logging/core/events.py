"""
Base event types for the centralized logging system.

This module defines the foundational event classes that all domain-specific
events inherit from. It uses only Python stdlib - no external dependencies.

Uses dataclasses for simplicity.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventLevel(Enum):
    """Event severity levels, matching Python logging levels."""

    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"

    @property
    def log_level(self) -> int:
        """Map to Python logging level integers."""
        import logging

        return {
            EventLevel.DEBUG: logging.DEBUG,
            EventLevel.INFO: logging.INFO,
            EventLevel.WARN: logging.WARNING,
            EventLevel.ERROR: logging.ERROR,
        }[self]

    @classmethod
    def ordered(cls) -> list["EventLevel"]:
        """Return levels in severity order (DEBUG < INFO < WARN < ERROR)."""
        return [cls.DEBUG, cls.INFO, cls.WARN, cls.ERROR]


class EventCategory(Enum):
    """
    Base event categories.

    Projects can use string categories for extension without modifying this enum.
    These are the common categories used across projects.
    """

    SYSTEM = "system"  # System lifecycle events
    LIFECYCLE = "lifecycle"  # Application lifecycle
    OPERATION = "operation"  # Generic operations
    ERROR = "error"  # Error events


@dataclass
class EventMeta:
    """
    Standard metadata attached to all events.

    This provides correlation and tracing information that helps connect
    related events across a single invocation or request.
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str | None = None
    invocation_id: str | None = None
    thread_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize metadata to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "invocation_id": self.invocation_id,
            "thread_id": self.thread_id,
            **self.extra,
        }


@dataclass
class BaseEvent:
    """
    Base class for all events in the system.

    All domain-specific events should inherit from this class.
    Events are immutable data structures that capture something that happened.

    Example:
        @dataclass
        class UserLoggedIn(BaseEvent):
            user_id: str
            login_method: str = "password"

            def __post_init__(self):
                super().__post_init__()
                self.level = EventLevel.INFO
                self.category = "auth"
                self.message = f"User {self.user_id} logged in via {self.login_method}"
    """

    # Required fields with defaults for inheritance
    level: EventLevel = field(default=EventLevel.INFO)
    category: str = field(default="system")
    message: str = field(default="")

    # Metadata - auto-populated
    meta: EventMeta = field(default_factory=EventMeta)

    # Additional structured data
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Hook for subclasses to set level, category, and message."""
        pass

    @property
    def event_type(self) -> str:
        """Return the event class name as the event type identifier."""
        return self.__class__.__name__

    @property
    def code(self) -> str:
        """Return a short event code. Subclasses must override."""
        return "X000"

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to dictionary for JSON logging."""
        return {
            "event_type": self.event_type,
            "code": self.code,
            "level": self.level.value,
            "category": self.category,
            "message": self.message,
            "meta": self.meta.to_dict(),
            "data": self.data,
        }
