"""Batch retry service — facade delegating to focused operation modules.

Implementation is split across:
- retry_ops.py: Retry-specific operations (resubmit missing records)
- retry_serialization.py: Serialize/deserialize BatchResult objects
- retry_polling.py: Batch polling and validation module import utilities
"""

import logging
import random
import time
from typing import TYPE_CHECKING, Any, Optional

# Import operation modules for delegation
from agent_actions.llm.batch.services import retry_ops as _retry
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
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

    def retrieve_results_with_retry(
        self,
        provider: BaseBatchClient,
        batch_id: str,
        output_directory: str,
        *,
        context_map: dict[str, Any],
        record_count: int | None = None,
        file_name: str | None = None,
        agent_config: dict[str, Any] | None = None,
    ) -> tuple[list[BatchResult], dict[str, RecoveryMetadata] | None]:
        """Retrieve batch results, resubmitting the records the provider did not return."""
        from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler

        retry_config = (agent_config or {}).get("retry")
        retry_enabled = retry_config and retry_config.get("enabled", True)
        max_attempts = retry_config.get("max_attempts", 3) if retry_config else 3
        base_delay = retry_config.get("base_delay", 5.0) if retry_config else 5.0
        max_delay = retry_config.get("max_delay", 120.0) if retry_config else 120.0

        all_results = retrieve_and_reconcile(
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=record_count,
            file_name=file_name,
        )

        # PHASE 1: RETRY — ensure we have all records we can get
        exhausted_recovery: dict[str, RecoveryMetadata] | None = None

        if retry_enabled:
            missing_ids = BatchResultReconciler.find_missing_ids(context_map, all_results)

            if missing_ids:
                record_failure_counts: dict[str, int] = {rid: 1 for rid in missing_ids}
                retry_attempts = 0

                while missing_ids and retry_attempts < max_attempts:
                    retry_attempts += 1
                    if retry_attempts > 1:
                        backoff = min(base_delay * (2 ** (retry_attempts - 2)), max_delay)
                        # Jitter adds 0-30% on top of backoff; total sleep may exceed max_delay.
                        jitter = random.uniform(0, backoff * 0.3)
                        sleep_time = backoff + jitter
                        logger.info(
                            "Batch retry backoff: sleeping %.1fs before attempt %d/%d",
                            sleep_time,
                            retry_attempts,
                            max_attempts,
                        )
                        time.sleep(sleep_time)
                    logger.info(
                        "Batch retry attempt %d/%d: resubmitting %d missing records",
                        retry_attempts,
                        max_attempts,
                        len(missing_ids),
                    )

                    retry_results = self._resubmit_missing_records(
                        provider=provider,
                        missing_ids=missing_ids,
                        context_map=context_map,
                        output_directory=output_directory,
                        file_name=file_name,
                        agent_config=agent_config,
                    )

                    (
                        all_results,
                        missing_ids,
                        record_failure_counts,
                        _,
                    ) = _retry.process_retry_results(
                        results=retry_results,
                        accumulated_results=all_results,
                        context_map=context_map,
                        record_failure_counts=record_failure_counts,
                        missing_ids=missing_ids,
                    )

                if retry_attempts > 0 and missing_ids:
                    exhausted_recovery = self.build_exhausted_recovery(
                        missing_ids, record_failure_counts, retry_attempts
                    )

        return all_results, exhausted_recovery

    def _resubmit_missing_records(
        self,
        provider: BaseBatchClient,
        missing_ids: set[str],
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str | None,
        agent_config: dict[str, Any] | None,
    ) -> list[BatchResult]:
        """Resubmit missing records as a new batch and wait for completion."""
        return _retry.resubmit_missing_records(
            storage_backend=self._storage_backend,
            provider=provider,
            missing_ids=missing_ids,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            agent_config=agent_config,
        )

    def submit_retry_batch(
        self,
        provider: BaseBatchClient,
        missing_ids: set[str],
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str | None,
        agent_config: dict[str, Any] | None,
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
