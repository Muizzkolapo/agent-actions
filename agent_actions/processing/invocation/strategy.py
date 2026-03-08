"""
Abstract base class for invocation strategies.

Part of Phase 3 (#891): Extract LLM invocation into strategy pattern.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, Protocol, TYPE_CHECKING

from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.processing.prepared_task import PreparedTask

if TYPE_CHECKING:
    from agent_actions.processing.types import ProcessingContext


class BatchProvider(Protocol):
    """Protocol for batch providers used by BatchStrategy."""

    def prepare_tasks(
        self, data: list[dict[str, Any]], agent_config: dict[str, Any]
    ) -> list[dict[str, Any]]: ...

    def submit_batch(
        self,
        tasks: list[dict[str, Any]],
        batch_name: str,
        output_directory: Optional[str] = None,
    ) -> tuple[str, str]: ...


class InvocationStrategy(ABC):
    """
    Abstract base for LLM invocation strategies.

    Strategy pattern allows same PreparedTask to be:
    - Executed immediately (OnlineStrategy)
    - Queued for batch submission (BatchStrategy)

    This enables unified preparation with flexible execution.
    """

    @abstractmethod
    def invoke(
        self,
        task: PreparedTask,
        context: "ProcessingContext",
    ) -> InvocationResult:
        """
        Invoke LLM for the prepared task.

        Args:
            task: PreparedTask from TaskPreparer
            context: ProcessingContext with agent config and state

        Returns:
            InvocationResult which may be:
            - Immediate (online): response available now
            - Deferred (batch): task queued, response later
            - Skipped: guard blocked execution
        """
        pass

    @abstractmethod
    def supports_recovery(self) -> bool:
        """
        Whether this strategy supports retry/reprompt recovery.

        Returns:
            True if strategy handles retry/reprompt internally
        """
        pass

    def cleanup(self) -> None:
        """
        Called when processing is complete.

        Override in subclasses that need cleanup (e.g., BatchStrategy.flush).
        Default implementation does nothing.
        """
        pass
