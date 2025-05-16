# Suggested content for validators/base_validator.py
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Dict, Optional

class BaseValidator(ABC):
    """
    Unified base class for all validators.

    This class provides a common structure for validation processes,
    including error and warning collection, and basic path utilities.
    Concrete validator classes should inherit from this class and
    implement the `validate` method to perform their specific checks.
    """

    def __init__(self) -> None:
        """Initializes the validator with empty error and warning lists."""
        self._errors: List[str] = []
        self._warnings: List[str] = []

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
        pass

    def add_error(self, message: str) -> None:
        """Adds a validation error message to the internal list."""
        self._errors.append(message)

    def add_warning(self, message: str) -> None:
        """Adds a validation warning message to the internal list."""
        self._warnings.append(message)

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

    # --- Static Utility Helper Methods ---
    @staticmethod
    def _ensure_path_exists(path: Path, path_description: Optional[str] = None) -> bool:
        """
        Checks if a given filesystem path exists.

        Args:
            path: The Path object to check.
            path_description: An optional description of the path (e.g., "Schema file")
                              for constructing more informative error messages by the caller.

        Returns:
            bool: True if the path exists, False otherwise.
        """
        # The path_description is for the caller to use when creating an error message.
        return path.exists()

    @staticmethod
    def _is_file(path: Path, path_description: Optional[str] = None) -> bool:
        """
        Checks if a given filesystem path exists and is a file.

        Args:
            path: The Path object to check.
            path_description: An optional description of the path.

        Returns:
            bool: True if the path exists and is a file, False otherwise.
        """
        return path.is_file()

    @staticmethod
    def _is_directory(path: Path, path_description: Optional[str] = None) -> bool:
        """
        Checks if a given filesystem path exists and is a directory.

        Args:
            path: The Path object to check.
            path_description: An optional description of the path.

        Returns:
            bool: True if the path exists and is a directory, False otherwise.
        """
        return path.is_dir()