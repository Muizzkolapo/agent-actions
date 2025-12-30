"""
Base class for agent entry validators.

All specialized validators inherit from this to ensure consistent interface.
"""

from abc import ABC, abstractmethod
from typing import List
from dataclasses import dataclass, field


@dataclass
class AgentEntryValidationResult:
    """
    Result from a single validator execution.

    Attributes:
        errors: List of validation error messages
        warnings: List of validation warning messages
        is_critical_failure: If True, stops the validation chain
    """

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    is_critical_failure: bool = False

    @classmethod
    def success(cls) -> "AgentEntryValidationResult":
        """Create a success result (no errors/warnings)."""
        return cls(errors=[], warnings=[], is_critical_failure=False)

    @classmethod
    def critical_failure(cls, error_message: str) -> "AgentEntryValidationResult":
        """Create a critical failure result that stops validation chain."""
        return cls(errors=[error_message], warnings=[], is_critical_failure=True)

    @classmethod
    def with_errors(cls, errors: List[str]) -> "AgentEntryValidationResult":
        """Create a result with errors (but not critical)."""
        return cls(errors=errors, warnings=[], is_critical_failure=False)

    @classmethod
    def with_warnings(cls, warnings: List[str]) -> "AgentEntryValidationResult":
        """Create a result with warnings only."""
        return cls(errors=[], warnings=warnings, is_critical_failure=False)


class BaseAgentEntryValidator(ABC):
    """
    Abstract base class for all agent entry validators.

    Each validator:
    - Receives the full entry and context
    - Performs specific validation checks
    - Returns a result with errors/warnings
    - Can signal critical failure to stop chain
    """

    def __repr__(self) -> str:
        """Return string representation of validator."""
        return f"{self.__class__.__name__}()"

    def is_valid(self) -> bool:
        """
        Check if validator is properly configured.

        Returns:
            bool: Always True (validators are stateless)
        """
        return True

    @abstractmethod
    def validate(self, context) -> AgentEntryValidationResult:
        """
        Perform validation on the agent entry.

        Args:
            context: AgentEntryValidationContext with entry, normalized data, etc.

        Returns:
            AgentEntryValidationResult with errors, warnings, and critical flag
        """
        raise NotImplementedError("Subclasses must implement validate()")

    def _format_error(self, description: str, message: str) -> str:
        """Helper to format error message consistently."""
        return f"{description} {message}"

    def _format_warning(self, description: str, message: str) -> str:
        """Helper to format warning message consistently."""
        return f"{description} {message}"
