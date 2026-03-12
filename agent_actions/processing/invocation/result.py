"""Invocation result type for LLM execution."""

from dataclasses import dataclass, field
from typing import Any, Optional

from agent_actions.processing.types import RecoveryMetadata


@dataclass
class InvocationResult:
    """Result of LLM invocation, covering both immediate (online) and deferred (batch) modes."""

    response: Optional[Any] = None
    executed: bool = False

    deferred: bool = False
    task_id: Optional[str] = None

    passthrough_fields: dict[str, Any] = field(default_factory=dict)
    recovery_metadata: Optional[RecoveryMetadata] = None

    @classmethod
    def immediate(
        cls,
        response: Any,
        executed: bool,
        passthrough_fields: Optional[dict[str, Any]] = None,
        recovery: Optional[RecoveryMetadata] = None,
    ) -> "InvocationResult":
        """Create an immediate execution result."""
        return cls(
            response=response,
            executed=executed,
            deferred=False,
            passthrough_fields=passthrough_fields or {},
            recovery_metadata=recovery,
        )

    @classmethod
    def queued(
        cls,
        task_id: str,
        passthrough_fields: Optional[dict[str, Any]] = None,
    ) -> "InvocationResult":
        """Create a queued (batch) result."""
        return cls(
            deferred=True,
            task_id=task_id,
            executed=False,
            passthrough_fields=passthrough_fields or {},
        )

    @classmethod
    def skipped(
        cls,
        passthrough_data: Optional[Any] = None,
        passthrough_fields: Optional[dict[str, Any]] = None,
    ) -> "InvocationResult":
        """Create a skipped (guard skip) result."""
        return cls(
            response=passthrough_data,
            executed=False,
            deferred=False,
            passthrough_fields=passthrough_fields or {},
        )

    @classmethod
    def filtered(cls) -> "InvocationResult":
        """Factory for filtered (guard filter) result."""
        return cls(
            response=None,
            executed=False,
            deferred=False,
        )

    @property
    def is_immediate(self) -> bool:
        """Return True if this is an immediate (non-deferred) result."""
        return not self.deferred

    @property
    def is_success(self) -> bool:
        """Return True if execution succeeded with a response."""
        return self.executed and self.response is not None
