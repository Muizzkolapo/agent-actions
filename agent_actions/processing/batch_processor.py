"""Batch processor: convenience facade over RecordProcessor for batch-mode callers."""

from typing import Any, Optional

from agent_actions.config.types import RunMode

from .invocation import BatchProvider, InvocationStrategy
from .record_processor import RecordProcessor
from .types import ProcessingContext, ProcessingResult


class BatchProcessor:
    """Batch-mode processing facade backed by a RecordProcessor.

    Callers that only need batch processing can use this class instead of
    instantiating RecordProcessor directly.
    """

    def __init__(
        self,
        agent_config: dict[str, Any],
        agent_name: str,
        strategy: InvocationStrategy | None = None,
        mode: RunMode = RunMode.ONLINE,
        provider: Optional["BatchProvider"] = None,
    ):
        self._processor = RecordProcessor(
            agent_config=agent_config,
            agent_name=agent_name,
            strategy=strategy,
            mode=mode,
            provider=provider,
        )

    def process_batch(self, items: list[Any], context: ProcessingContext) -> list[ProcessingResult]:
        """Process multiple records, capturing per-item failures without aborting the batch."""
        return self._processor.process_batch(items, context)
