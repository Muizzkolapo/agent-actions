"""
Batch invocation strategy.

Part of Phase 3 (#891): Extract LLM invocation into strategy pattern.

Queues tasks for batch API submission instead of immediate execution.
"""

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.processing.invocation.strategy import BatchProvider, InvocationStrategy
from agent_actions.processing.prepared_task import PreparedTask

if TYPE_CHECKING:
    from agent_actions.processing.types import ProcessingContext

logger = logging.getLogger(__name__)


@dataclass
class BatchSubmissionResult:
    """
    Result of batch submission via flush().

    Attributes:
        batch_id: Provider-assigned batch identifier (None if no tasks)
        task_count: Number of tasks submitted
        context_map: Map of task_id -> context metadata for result reconciliation
    """

    batch_id: Optional[str]
    task_count: int
    context_map: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Whether any tasks were submitted."""
        return self.task_count == 0


class BatchStrategy(InvocationStrategy):
    """
    Queues tasks for batch API submission.

    Instead of executing immediately, tasks are queued and submitted
    together via flush(). Results are retrieved asynchronously.

    Example:
        strategy = BatchStrategy(provider)

        # Queue tasks
        for item in items:
            result = strategy.invoke(prepared_task, context)
            # result.deferred == True

        # Submit batch
        submission = strategy.flush()
        print(f"Submitted batch {submission.batch_id} with {submission.task_count} tasks")

    Lifecycle:
        1. Create strategy with provider
        2. Call invoke() for each task (queues internally)
        3. Call flush() to submit all queued tasks
        4. Use context_map to reconcile results when batch completes
    """

    def __init__(self, provider: BatchProvider):
        """
        Initialize BatchStrategy.

        Args:
            provider: Batch provider instance (e.g., OpenAIBatchClient)
        """
        self._provider = provider
        self._agent_config: Optional[dict[str, Any]] = None
        self._queued: list[PreparedTask] = []
        self._context_map: dict[str, Any] = {}

    def invoke(
        self,
        task: PreparedTask,
        context: "ProcessingContext",
    ) -> InvocationResult:
        """
        Queue task for batch submission.

        Does not execute immediately. Call flush() to submit all queued tasks.

        Args:
            task: PreparedTask from TaskPreparer
            context: ProcessingContext with agent config

        Returns:
            InvocationResult with deferred=True and task_id
        """
        # Defensive: processor handles guard routing before invoke(), but
        # strategies must also handle it for direct callers bypassing processor.
        if not task.should_execute:
            # Track in context map for result reconciliation
            self._context_map[task.target_id] = {
                "status": task.guard_behavior or "filtered",
                "original": task.original_content,
                "passthrough_fields": task.passthrough_fields,
                "source_guid": task.source_guid,
                "executed": False,
            }

            if task.is_passthrough:
                return InvocationResult.skipped(
                    passthrough_data=task.original_content,
                    passthrough_fields=task.passthrough_fields,
                )
            return InvocationResult.filtered()

        # Capture agent_config once. Deep copy guards against the caller mutating
        # agent_config between invoke() and flush() (e.g. per-record overrides).
        if self._agent_config is None:
            self._agent_config = copy.deepcopy(context.agent_config)

        # Queue task for batch submission
        self._queued.append(task)

        # Track in context map (warn on duplicate)
        if task.target_id in self._context_map:
            logger.warning("Duplicate target_id %s, overwriting", task.target_id)
        self._context_map[task.target_id] = {
            "status": "included",
            "original": task.original_content,
            "passthrough_fields": task.passthrough_fields,
            "source_guid": task.source_guid,
            "executed": True,  # Will be executed when batch runs
        }

        return InvocationResult.queued(
            task_id=task.target_id,
            passthrough_fields=task.passthrough_fields,
        )

    def supports_recovery(self) -> bool:
        """BatchStrategy does not support inline retry/reprompt."""
        return False

    def flush(
        self,
        batch_name: Optional[str] = None,
        output_directory: Optional[str] = None,
    ) -> BatchSubmissionResult:
        """
        Submit all queued tasks to batch API.

        Args:
            batch_name: Name for the batch job (auto-generated if not provided)
            output_directory: Output directory for batch artifacts

        Returns:
            BatchSubmissionResult with batch_id and context_map
        """
        if not self._queued:
            snapshot = self._context_map.copy()
            self._context_map = {}
            self._agent_config = None
            return BatchSubmissionResult(
                batch_id=None,
                task_count=0,
                context_map=snapshot,
            )

        # Build batch tasks in provider-ready format
        batch_tasks = []
        for task in self._queued:
            batch_task = {
                "target_id": task.target_id,
                "content": task.llm_context,
                "prompt": task.formatted_prompt,
            }
            batch_tasks.append(batch_task)

        # Prepare tasks in provider-specific format and submit.
        # State is always reset in `finally` to prevent stale tasks from
        # leaking into a subsequent flush() if the caller catches and
        # reuses this strategy instance after a failure.
        task_count = len(batch_tasks)
        context_snapshot = self._context_map.copy()
        try:
            formatted_tasks = self._provider.prepare_tasks(batch_tasks, self._agent_config)
            resolved_name = batch_name or f"batch-{task_count}-tasks"
            batch_id, _status = self._provider.submit_batch(
                formatted_tasks, resolved_name, output_directory
            )
        finally:
            self._queued = []
            self._context_map = {}
            self._agent_config = None

        logger.info(
            "BatchStrategy submitted %d tasks as batch %s",
            task_count,
            batch_id,
        )

        return BatchSubmissionResult(
            batch_id=batch_id,
            task_count=task_count,
            context_map=context_snapshot,
        )

    def cleanup(self) -> None:
        """
        Cleanup strategy state.

        Called when processing is complete. Logs warning if tasks remain unflushed.
        """
        if self._queued:
            logger.warning(
                "BatchStrategy cleanup called with %d unflushed tasks",
                len(self._queued),
            )
            self._queued = []
            self._context_map = {}
            self._agent_config = None

    def get_prepared_tasks(self) -> list[dict[str, Any]]:
        """
        Get queued tasks in provider-ready format.

        Used by BatchTaskPreparator to access prepared tasks for submission.

        Returns:
            List of task dicts with target_id, content, prompt
        """
        return [
            {
                "target_id": task.target_id,
                "content": task.llm_context,
                "prompt": task.formatted_prompt,
            }
            for task in self._queued
        ]

    @property
    def queued_count(self) -> int:
        """Number of tasks currently queued."""
        return len(self._queued)

    @property
    def context_map(self) -> dict[str, Any]:
        """Access context map for result reconciliation."""
        return self._context_map
