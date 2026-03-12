"""Abstract base class for invocation strategies."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol

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
        output_directory: str | None = None,
    ) -> tuple[str, str]: ...


class InvocationStrategy(ABC):
    """Abstract base for LLM invocation strategies (online or batch)."""

    @abstractmethod
    def invoke(
        self,
        task: PreparedTask,
        context: "ProcessingContext",
    ) -> InvocationResult:
        """Invoke LLM for the prepared task, returning an InvocationResult."""
        pass

    @abstractmethod
    def supports_recovery(self) -> bool:
        """Return True if this strategy handles retry/reprompt internally."""
        pass

    def cleanup(self) -> None:  # noqa: B027
        """Called when processing is complete. Override in subclasses that need cleanup."""
        pass
