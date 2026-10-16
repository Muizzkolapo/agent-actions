"""Batch retry service — facade delegating to focused operation modules.

Implementation is split across:
- retry_ops.py: Retry-specific operations (submit a retry batch, merge its results)
- retry_serialization.py: Serialize/deserialize BatchResult objects
- retry_polling.py: Validation module import
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

# Import operation modules for delegation
from agent_actions.llm.batch.services import retry_ops as _retry
from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
from agent_actions.processing.types import RecoveryMetadata

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class BatchRetryService:
    """Handles retry logic for batch processing.

    This is a thin facade — each method delegates to a focused operation
    module. See module docstrings in retry_ops, retry_serialization, and
    retry_polling for details.
    """

    def __init__(
        self,
        action_indices: dict[str, int] | None = None,
        dependency_configs: dict[str, dict] | None = None,
        storage_backend: Optional["StorageBackend"] = None,
    ):
        self._action_indices = action_indices or {}
        self._dependency_configs = dependency_configs or {}
        self._storage_backend = storage_backend

    # =========================================================================
    # RETRY OPERATIONS (delegated to retry_ops)
    # =========================================================================

    def submit_retry_batch(
        self,
        provider: BaseBatchClient,
        missing_ids: set[str],
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str | None,
        agent_config: dict[str, Any] | None,
        workflow_metadata: dict[str, Any] | None = None,
    ) -> tuple[str, int] | None:
        """Submit a retry batch for missing records without blocking."""
        return _retry.submit_retry_batch(
            storage_backend=self._storage_backend,
            provider=provider,
            missing_ids=missing_ids,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            agent_config=agent_config,
            action_indices=self._action_indices,
            dependency_configs=self._dependency_configs,
            workflow_metadata=workflow_metadata,
        )

    def process_retry_results(
        self,
        results: list[BatchResult],
        accumulated_results: list[BatchResult],
        context_map: dict[str, Any],
        record_failure_counts: dict[str, int],
        missing_ids: set[str],
    ) -> tuple[list[BatchResult], set[str], dict[str, int], dict[str, RecoveryMetadata] | None]:
        """Process retry batch results and determine if more retries are needed."""
        return _retry.process_retry_results(
            results=results,
            accumulated_results=accumulated_results,
            context_map=context_map,
            record_failure_counts=record_failure_counts,
            missing_ids=missing_ids,
        )

    def build_exhausted_recovery(
        self,
        missing_ids: set[str],
        record_failure_counts: dict[str, int],
        retry_attempts: int = 0,
    ) -> dict[str, RecoveryMetadata]:
        """Build recovery metadata for records that exhausted all retry attempts."""
        return _retry.build_exhausted_recovery(
            missing_ids=missing_ids,
            record_failure_counts=record_failure_counts,
            retry_attempts=retry_attempts,
        )
