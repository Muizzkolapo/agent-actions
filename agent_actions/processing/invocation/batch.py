"""Batch invocation strategy for queuing tasks for batch API submission."""

import copy
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_actions.config.types import ActionConfigDict
from agent_actions.processing.invocation.result import InvocationResult
from agent_actions.processing.invocation.strategy import BatchProvider, InvocationStrategy
from agent_actions.processing.prepared_task import PreparedTask

if TYPE_CHECKING:
    from agent_actions.processing.types import ProcessingContext

logger = logging.getLogger(__name__)


@dataclass
class BatchSubmissionResult:
    """Result of batch submission via flush()."""

    batch_id: str | None
    task_count: int
    context_map: dict[str, Any] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """Return True if no tasks were submitted."""
        return self.task_count == 0


class BatchStrategy(InvocationStrategy):
    """Queues tasks for batch API submission; call flush() to submit."""

    def __init__(self, provider: BatchProvider):
        self._provider = provider
        self._agent_config: ActionConfigDict | dict[str, Any] | None = None
        self._queued: list[PreparedTask] = []
        self._context_map: dict[str, Any] = {}

    def invoke(
        self,
        task: PreparedTask,
        context: "ProcessingContext",
    ) -> InvocationResult:
        """Queue task for batch submission; returns deferred InvocationResult."""
        if not task.should_execute:
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

        # Deep copy guards against caller mutating agent_config between invoke() and flush()
        if self._agent_config is None:
            self._agent_config = copy.deepcopy(context.agent_config)

        self._queued.append(task)

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
        batch_name: str | None = None,
        output_directory: str | None = None,
    ) -> BatchSubmissionResult:
        """Submit all queued tasks to batch API and reset internal state."""
        if not self._queued:
            snapshot = self._context_map.copy()
            self._context_map = {}
            self._agent_config = None
            return BatchSubmissionResult(
                batch_id=None,
                task_count=0,
                context_map=snapshot,
            )

        batch_tasks = []
        for task in self._queued:
            batch_task = {
                "target_id": task.target_id,
                "content": task.llm_context,
                "prompt": task.formatted_prompt,
            }
            batch_tasks.append(batch_task)

        task_count = len(batch_tasks)
        context_snapshot = self._context_map.copy()
        if self._agent_config is None:
            raise RuntimeError("BatchStrategy._agent_config is None at flush time")
        formatted_tasks = self._provider.prepare_tasks(batch_tasks, dict(self._agent_config))
        resolved_name = batch_name or f"batch-{task_count}-tasks"
        batch_id, _status = self._provider.submit_batch(
            formatted_tasks, resolved_name, output_directory
        )

        # Clear state only after successful submission — transient failures
        # preserve queued tasks so the caller can retry flush().
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
        """Clean up strategy state, warning if tasks remain unflushed."""
        if self._queued:
            logger.warning(
                "BatchStrategy cleanup called with %d unflushed tasks",
                len(self._queued),
            )
            self._queued = []
            self._context_map = {}
            self._agent_config = None

    def get_prepared_tasks(self) -> list[dict[str, Any]]:
        """Return queued tasks in provider-ready format."""
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
