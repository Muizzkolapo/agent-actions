"""Base class for agent entry validators."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentEntryValidationResult:
    """Result from a single validator execution."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
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
    def with_errors(cls, errors: list[str]) -> "AgentEntryValidationResult":
        """Create a result with errors (but not critical)."""
        return cls(errors=errors, warnings=[], is_critical_failure=False)

    @classmethod
    def with_warnings(cls, warnings: list[str]) -> "AgentEntryValidationResult":
        """Create a result with warnings only."""
        return cls(errors=[], warnings=warnings, is_critical_failure=False)


class BaseAgentEntryValidator(ABC):
    """Abstract base class for all agent entry validators."""

    def __repr__(self) -> str:
        """Return string representation of validator."""
        return f"{self.__class__.__name__}()"

    @abstractmethod
    def validate(self, context) -> AgentEntryValidationResult:
        """Perform validation on the agent entry."""
        raise NotImplementedError("Subclasses must implement validate()")
