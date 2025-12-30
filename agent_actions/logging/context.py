"""Correlation context management for logging."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4


@dataclass
class ExecutionContext:
    """Context information for a single workflow execution."""

    correlation_id: str
    workflow_name: Optional[str] = None
    agent_name: Optional[str] = None
    agent_index: Optional[int] = None
    batch_id: Optional[str] = None
    item_id: Optional[str] = None
    extra: dict = field(default_factory=dict)


# Thread-safe context storage using contextvars
_execution_context: ContextVar[Optional[ExecutionContext]] = ContextVar(
    "execution_context",
    default=None,
)


class CorrelationContext:
    """Manages execution context for logging correlation.

    This class provides thread-safe context management using Python's contextvars.
    All log entries within a workflow execution can be correlated using the
    correlation_id generated when a workflow starts.

    Example:
        >>> ctx = CorrelationContext.start_workflow('my-workflow')
        >>> print(ctx.correlation_id)  # 'a1b2c3d4'
        >>> CorrelationContext.set_agent('agent-1', 0)
        >>> # All logs now include correlation_id and agent info
        >>> CorrelationContext.clear_context()
    """

    @staticmethod
    def generate_correlation_id() -> str:
        """Generate a unique correlation ID.

        Returns:
            8-character unique identifier for log correlation.
        """
        return str(uuid4())[:8]

    @staticmethod
    def get_context() -> Optional[ExecutionContext]:
        """Get current execution context.

        Returns:
            Current ExecutionContext or None if not in a workflow execution.
        """
        return _execution_context.get()

    @staticmethod
    def set_context(ctx: ExecutionContext) -> None:
        """Set execution context for current thread/coroutine.

        Args:
            ctx: ExecutionContext to set as current.
        """
        _execution_context.set(ctx)

    @staticmethod
    def clear_context() -> None:
        """Clear execution context."""
        _execution_context.set(None)

    @classmethod
    def start_workflow(cls, workflow_name: str) -> ExecutionContext:
        """Initialize context for workflow execution.

        Args:
            workflow_name: Name of the workflow being executed.

        Returns:
            New ExecutionContext with generated correlation_id.
        """
        ctx = ExecutionContext(
            correlation_id=cls.generate_correlation_id(),
            workflow_name=workflow_name,
        )
        cls.set_context(ctx)
        return ctx

    @classmethod
    def set_agent(cls, agent_name: str, agent_index: int) -> None:
        """Update context with current agent information.

        Args:
            agent_name: Name of the agent being executed.
            agent_index: Index of the agent in the workflow.
        """
        ctx = cls.get_context()
        if ctx:
            ctx.agent_name = agent_name
            ctx.agent_index = agent_index

    @classmethod
    def set_batch(cls, batch_id: str) -> None:
        """Update context with batch information.

        Args:
            batch_id: Identifier for the current batch.
        """
        ctx = cls.get_context()
        if ctx:
            ctx.batch_id = batch_id

    @classmethod
    def set_item(cls, item_id: str) -> None:
        """Update context with item information.

        Args:
            item_id: Identifier for the current item being processed.
        """
        ctx = cls.get_context()
        if ctx:
            ctx.item_id = item_id

    @classmethod
    def add_extra(cls, key: str, value: str) -> None:
        """Add extra context information.

        Args:
            key: Context key name.
            value: Context value.
        """
        ctx = cls.get_context()
        if ctx:
            ctx.extra[key] = value

    @classmethod
    def get_correlation_id(cls) -> Optional[str]:
        """Get current correlation ID if available.

        Returns:
            Current correlation_id or None.
        """
        ctx = cls.get_context()
        return ctx.correlation_id if ctx else None
