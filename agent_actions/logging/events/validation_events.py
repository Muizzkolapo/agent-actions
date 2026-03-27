"""Validation, data parsing, guard, and recovery events (V/D/G/R prefixes)."""

from dataclasses import dataclass
from typing import Any

from agent_actions.logging.core.events import BaseEvent, EventLevel
from agent_actions.logging.events.types import EventCategories, _safe_value_repr

__all__ = [
    "ValidationStartEvent",
    "ValidationCompleteEvent",
    "ValidationErrorEvent",
    "ValidationWarningEvent",
    "DataParsingErrorEvent",
    "DataLoadingErrorEvent",
    "DataValidationErrorEvent",
    "GuardEvaluationTimeoutEvent",
    "GuardEvaluationErrorEvent",
    "RetryExhaustedEvent",
    "RepromptValidationFailedEvent",
    "RecoveryErrorEvent",
]


@dataclass
class ValidationStartEvent(BaseEvent):
    """Fired when validation begins."""

    target: str = ""
    validator: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG
        self.category = EventCategories.VALIDATION
        self.message = f"Validating {self.target} ({self.validator})"
        self.data = {
            "target": self.target,
            "validator": self.validator,
        }

    @property
    def code(self) -> str:
        return "V001"


@dataclass
class ValidationCompleteEvent(BaseEvent):
    """Fired when validation completes successfully."""

    target: str = ""
    validator: str = ""
    elapsed_time: float = 0.0
    warning_count: int = 0
    error_count: int = 0

    def __post_init__(self) -> None:
        self.level = EventLevel.DEBUG if self.error_count == 0 else EventLevel.ERROR
        self.category = EventCategories.VALIDATION
        status_parts = []
        if self.warning_count > 0:
            status_parts.append(f"{self.warning_count} warnings")
        if self.error_count > 0:
            status_parts.append(f"{self.error_count} errors")
        status_str = f" ({', '.join(status_parts)})" if status_parts else ""
        result = "passed" if self.error_count == 0 else "failed"
        self.message = f"Validation {result}: {self.target} in {self.elapsed_time:.2f}s{status_str}"
        self.data = {
            "target": self.target,
            "validator": self.validator,
            "elapsed_time": self.elapsed_time,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
        }

    @property
    def code(self) -> str:
        return "V002"


@dataclass
class ValidationErrorEvent(BaseEvent):
    """Fired when validation finds an error."""

    target: str = ""
    field: str = ""
    error: str = ""
    value: Any = None

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.VALIDATION
        location = f"{self.target}.{self.field}" if self.field else self.target
        value_repr = _safe_value_repr(self.value)
        value_str = f' (got: "{value_repr}")' if value_repr else ""
        self.message = f"VALIDATION ERROR in {location}: {self.error}{value_str}"
        self.data = {
            "target": self.target,
            "field": self.field,
            "error": self.error,
            "value": value_repr if value_repr else None,
        }

    @property
    def code(self) -> str:
        return "V003"


@dataclass
class ValidationWarningEvent(BaseEvent):
    """Fired when validation finds a warning (non-fatal issue)."""

    target: str = ""
    field: str = ""
    warning: str = ""
    value: Any = None

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.VALIDATION
        location = f"{self.target}.{self.field}" if self.field else self.target
        value_repr = _safe_value_repr(self.value)
        value_str = f" (value: {value_repr})" if value_repr else ""
        self.message = f"VALIDATION WARNING in {location}: {self.warning}{value_str}"
        self.data = {
            "target": self.target,
            "field": self.field,
            "warning": self.warning,
            "value": value_repr if value_repr else None,
        }

    @property
    def code(self) -> str:
        return "V004"


@dataclass
class DataParsingErrorEvent(BaseEvent):
    """Fired when data parsing fails."""

    file_path: str = ""
    format: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.DATA
        self.message = f"Failed to parse {self.format} from {self.file_path}: {self.error}"
        self.data = {
            "file_path": self.file_path,
            "format": self.format,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "D001"


@dataclass
class DataLoadingErrorEvent(BaseEvent):
    """Fired when data loading fails."""

    file_path: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.DATA
        self.message = f"Failed to load data from {self.file_path}: {self.error}"
        self.data = {
            "file_path": self.file_path,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "D002"


@dataclass
class DataValidationErrorEvent(BaseEvent):
    """Fired when data validation fails."""

    file_path: str = ""
    validation_error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.DATA
        self.message = f"Data validation failed for {self.file_path}: {self.validation_error}"
        self.data = {
            "file_path": self.file_path,
            "validation_error": self.validation_error,
        }

    @property
    def code(self) -> str:
        return "D003"


@dataclass
class GuardEvaluationTimeoutEvent(BaseEvent):
    """Fired when guard evaluation times out."""

    guard_clause: str = ""
    timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.GUARD
        self.message = (
            f"Guard evaluation timed out after {self.timeout_seconds}s: {self.guard_clause}"
        )
        self.data = {
            "guard_clause": self.guard_clause,
            "timeout_seconds": self.timeout_seconds,
        }

    @property
    def code(self) -> str:
        return "G001"


@dataclass
class GuardEvaluationErrorEvent(BaseEvent):
    """Fired when guard evaluation fails with error."""

    guard_clause: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.GUARD
        self.message = f"Guard evaluation failed: {self.error}"
        self.data = {
            "guard_clause": self.guard_clause,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "G002"


@dataclass
class RetryExhaustedEvent(BaseEvent):
    """Fired when retries are exhausted."""

    attempt: int = 0
    max_attempts: int = 0
    reason: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.RECOVERY
        self.message = (
            f"Retry exhausted after {self.attempt}/{self.max_attempts} attempts: {self.reason}"
        )
        self.data = {
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "reason": self.reason,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "R001"


@dataclass
class RepromptValidationFailedEvent(BaseEvent):
    """Fired when reprompt validation fails."""

    action_name: str = ""
    attempt: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.WARN
        self.category = EventCategories.RECOVERY
        self.message = f"Reprompt validation failed for '{self.action_name}' (attempt {self.attempt}): {self.error}"
        self.data = {
            "action_name": self.action_name,
            "attempt": self.attempt,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "R002"


@dataclass
class RecoveryErrorEvent(BaseEvent):
    """Fired when recovery mechanism itself fails."""

    recovery_type: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.level = EventLevel.ERROR
        self.category = EventCategories.RECOVERY
        self.message = f"Recovery mechanism failed ({self.recovery_type}): {self.error}"
        self.data = {
            "recovery_type": self.recovery_type,
            "error": self.error,
        }

    @property
    def code(self) -> str:
        return "R003"
