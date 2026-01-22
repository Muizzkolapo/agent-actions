"""
Base validator class for all validation operations.

Provides common validation infrastructure including error/warning collection
and utility methods for path validation.
"""

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Dict, Optional

from agent_actions.logging import fire_event
from agent_actions.logging.events import (
    ValidationCompleteEvent,
    ValidationErrorEvent,
    ValidationStartEvent,
    ValidationWarningEvent,
)


class BaseValidator(ABC):
    """
    Unified base class for all validators.

    This class provides a common structure for validation processes,
    including error and warning collection, and basic path utilities.
    Concrete validator classes should inherit from this class and
    implement the `validate` method to perform their specific checks.
    """

    def __init__(self, fire_events: bool = True) -> None:
        """Initializes the validator with empty error and warning lists.

        Args:
            fire_events: Whether to fire validation events. Defaults to True.
                         Set to False to disable event firing (useful for testing
                         or when validation is called from within other validators).
        """
        self._errors: List[str] = []
        self._warnings: List[str] = []
        self._validation_target: str = ""
        self._validation_start_time: float = 0.0
        self._fire_events: bool = fire_events

    @property
    def validator_name(self) -> str:
        """Return the validator name for event logging."""
        return self.__class__.__name__

    @abstractmethod
    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Performs the core validation logic for the specific validator.

        This method must be implemented by all concrete validator subclasses.
        It should use `add_error` and `add_warning` to record any issues found.

        Args:
            data: The primary data or resource to be validated.
                  The exact nature of this argument (e.g., file path, dictionary,
                  object instance) will depend on the concrete validator.
            config: Optional dictionary containing configuration parameters or
                    additional context needed for the validation (e.g., specific
                    rules, settings, related file paths).

        Returns:
            bool: True if validation is successful (no errors reported),
                  False otherwise.
        """
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

    def get_errors(self) -> List[str]:
        """Returns a list of all validation errors recorded."""
        return self._errors

    def get_warnings(self) -> List[str]:
        """Returns a list of all validation warnings recorded."""
        return self._warnings

    def clear_errors(self) -> None:
        """Clears all recorded validation errors."""
        self._errors = []

    def clear_warnings(self) -> None:
        """Clears all recorded validation warnings."""
        self._warnings = []

    def has_errors(self) -> bool:
        """
        Checks if any errors have been recorded during validation.

        Returns:
            bool: True if errors have been added, False otherwise.
        """
        return bool(self._errors)

    def _prepare_validation(self, data: Any, target: str = "") -> bool:
        """
        Common validation preparation: clear errors/warnings and check dict type.

        This helper method reduces code duplication across validators.

        Args:
            data: Data to validate (should be a dict)
            target: Target name for validation events

        Returns:
            bool: True if data is a dict and validation can proceed,
                  False if data is not a dict (error added)
        """
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
        """
        Complete validation and fire the completion event.

        Returns:
            bool: True if validation passed (no errors), False otherwise.
        """
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
        """
        Checks if a given filesystem path exists.

        Args:
            path: The Path object to check.

        Returns:
            bool: True if the path exists, False otherwise.
        """
        return path.exists()

    @staticmethod
    def _is_file(path: Path) -> bool:
        """
        Checks if a given filesystem path exists and is a file.

        Args:
            path: The Path object to check.

        Returns:
            bool: True if the path exists and is a file, False otherwise.
        """
        return path.is_file()

    @staticmethod
    def _is_directory(path: Path) -> bool:
        """
        Checks if a given filesystem path exists and is a directory.

        Args:
            path: The Path object to check.

        Returns:
            bool: True if the path exists and is a directory, False otherwise.
        """
        return path.is_dir()
