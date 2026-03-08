"""
Invocation result type for LLM execution.

Part of Phase 3 (#891): Extract LLM invocation into strategy pattern.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from agent_actions.processing.types import RecoveryMetadata


@dataclass
class InvocationResult:
    """
    Result of LLM invocation (immediate or deferred).

    This unified result type handles both:
    - Online mode: immediate response available
    - Batch mode: task queued, response retrieved later

    Attributes:
        response: LLM response (None if deferred or skipped)
        executed: Whether LLM was actually executed
        deferred: Whether execution is deferred (batch mode)
        task_id: Task identifier for deferred results
        passthrough_fields: Fields to merge into output
        recovery_metadata: Recovery tracking (retry/reprompt attempts)
    """

    # Execution result
    response: Optional[Any] = None
    executed: bool = False

    # Deferred execution (batch mode)
    deferred: bool = False
    task_id: Optional[str] = None

    # Context preservation
    passthrough_fields: dict[str, Any] = field(default_factory=dict)

    # Recovery tracking
    recovery_metadata: Optional[RecoveryMetadata] = None

    @classmethod
    def immediate(
        cls,
        response: Any,
        executed: bool,
        passthrough_fields: Optional[dict[str, Any]] = None,
        recovery: Optional[RecoveryMetadata] = None,
    ) -> "InvocationResult":
        """
        Factory for immediate execution result.

        Args:
            response: LLM response
            executed: Whether execution completed
            passthrough_fields: Fields to pass through to output
            recovery: Recovery metadata if retry/reprompt occurred
        """
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
        """
        Factory for queued (batch) result.

        Args:
            task_id: Unique identifier for retrieving result later
            passthrough_fields: Fields to pass through to output
        """
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
        """
        Factory for skipped (guard skip) result.

        Args:
            passthrough_data: Original content to pass through
            passthrough_fields: Fields to merge into output
        """
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
        """Whether this is an immediate (non-deferred) result."""
        return not self.deferred

    @property
    def is_success(self) -> bool:
        """Whether execution succeeded with a response."""
        return self.executed and self.response is not None
