"""Base validator class for all validation operations."""

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import (
    ValidationCompleteEvent,
    ValidationErrorEvent,
    ValidationStartEvent,
    ValidationWarningEvent,
)


class BaseValidator(ABC):
    """Unified base class for all validators with error/warning collection."""

    def __init__(self, fire_events: bool = True) -> None:
        """Initialize the validator with empty error and warning lists."""
        self._errors: list[str] = []
        self._warnings: list[str] = []
        self._validation_target: str = ""
        self._validation_start_time: float = 0.0
        self._fire_events: bool = fire_events

    @property
    def validator_name(self) -> str:
        """Return the validator name for event logging."""
        return self.__class__.__name__

    @abstractmethod
    def validate(self, data: Any, config: dict[str, Any] | None = None) -> bool:
        """Perform validation; return True if no errors found."""
        raise NotImplementedError("Subclasses must implement validate()")

    def add_error(self, message: str, field: str = "", value: Any = None) -> None:
        """Adds a validation error message to the internal list and fires an event."""
        self._errors.append(message)
        if self._fire_events:
            fire_event(
                ValidationErrorEvent(
                    target=self._validation_target or self.validator_name,
                    field=field,
                    error=message,
                    value=value,
                )
            )

    def add_warning(self, message: str, field: str = "", value: Any = None) -> None:
        """Adds a validation warning message to the internal list and fires an event."""
        self._warnings.append(message)
        if self._fire_events:
            fire_event(
                ValidationWarningEvent(
                    target=self._validation_target or self.validator_name,
                    field=field,
                    warning=message,
                    value=value,
                )
            )

    def get_errors(self) -> list[str]:
        """Return all recorded validation errors."""
        return self._errors

    def get_warnings(self) -> list[str]:
        """Return all recorded validation warnings."""
        return self._warnings

    def clear_errors(self) -> None:
        """Clear all recorded validation errors."""
        self._errors = []

    def clear_warnings(self) -> None:
        """Clear all recorded validation warnings."""
        self._warnings = []

    def has_errors(self) -> bool:
        """Return True if any errors have been recorded."""
        return bool(self._errors)

    def _prepare_validation(self, data: Any, target: str = "") -> bool:
        """Clear state, fire start event, and verify data is a dict."""
        self.clear_errors()
        self.clear_warnings()
        self._validation_target = target or self.validator_name
        self._validation_start_time = time.time()

        if self._fire_events:
            fire_event(
                ValidationStartEvent(
                    target=self._validation_target,
                    validator=self.validator_name,
                )
            )

        if not isinstance(data, dict):
            self.add_error("Validation data must be a dictionary.")
            return False
        return True

    def _complete_validation(self) -> bool:
        """Fire completion event and return True if no errors."""
        elapsed_time = time.time() - self._validation_start_time
        has_errors = self.has_errors()

        if self._fire_events:
            fire_event(
                ValidationCompleteEvent(
                    target=self._validation_target,
                    validator=self.validator_name,
                    elapsed_time=elapsed_time,
                    warning_count=len(self._warnings),
                    error_count=len(self._errors),
                )
            )

        return not has_errors

    # --- Static Utility Helper Methods ---
    @staticmethod
    def _ensure_path_exists(path: Path) -> bool:
        """Return True if the path exists."""
        return path.exists()

    @staticmethod
    def _is_file(path: Path) -> bool:
        """Return True if the path exists and is a file."""
        return path.is_file()

    @staticmethod
    def _is_directory(path: Path) -> bool:
        """Return True if the path exists and is a directory."""
        return path.is_dir()
