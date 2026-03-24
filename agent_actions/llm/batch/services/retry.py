"""Batch retry service — facade delegating to focused operation modules.

Implementation is split across:
- retry_ops.py: Retry-specific operations (resubmit missing records)
- reprompt_ops.py: Reprompt/validation operations (validate and resubmit failures)
- retry_serialization.py: Serialize/deserialize BatchResult objects
- retry_polling.py: Batch polling and validation module import utilities
"""

import logging
from typing import TYPE_CHECKING, Any, Optional

# Import operation modules for delegation
from agent_actions.llm.batch.services import reprompt_ops as _reprompt
from agent_actions.llm.batch.services import retry_ops as _retry

# Re-export module-level functions for backward compatibility.
# Tests and callers patch/import these from "agent_actions.llm.batch.services.retry".
from agent_actions.llm.batch.services.retry_polling import (
    import_validation_module as _import_validation_module,  # noqa: F401
)
from agent_actions.llm.batch.services.retry_polling import wait_for_batch_completion  # noqa: F401
from agent_actions.llm.batch.services.retry_serialization import (  # noqa: F401
    deserialize_results,
    serialize_results,
)
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile  # noqa: F401
from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
from agent_actions.processing.types import RecoveryMetadata

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class BatchRetryService:
    """Handles retry and reprompt logic for batch processing.

    This is a thin facade — each method delegates to a focused operation
    module. See module docstrings in retry_ops, reprompt_ops,
    retry_serialization, and retry_polling for details.
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
        """Retrieve batch results with retry for missing records.

        Phase 1 (retry) is handled by retry_ops; Phase 2 (validation)
        is handled by reprompt_ops.
        """
        from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler

        retry_config = (agent_config or {}).get("retry")
        retry_enabled = retry_config and retry_config.get("enabled", True)
        max_attempts = retry_config.get("max_attempts", 3) if retry_config else 3

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
            expected_ids = BatchResultReconciler.collect_expected_custom_ids(context_map)
            received_ids = BatchResultReconciler.collect_result_custom_ids(all_results)
            missing_ids = expected_ids - received_ids

            if missing_ids:
                from datetime import UTC, datetime

                record_failure_counts: dict[str, int] = {rid: 1 for rid in missing_ids}
                retry_attempts = 0

                while missing_ids and retry_attempts < max_attempts:
                    retry_attempts += 1
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

                    if retry_results:
                        from agent_actions.processing.types import RetryMetadata

                        for res in retry_results:
                            if res.success:
                                custom_id = res.custom_id
                                failures = record_failure_counts.get(custom_id, 1)
                                res.recovery_metadata = RecoveryMetadata(
                                    retry=RetryMetadata(
                                        attempts=failures + 1,
                                        failures=failures,
                                        succeeded=True,
                                        reason="missing",
                                        timestamp=datetime.now(UTC).isoformat(),
                                    )
                                )

                        all_results.extend(retry_results)

                        successful_retry = [r for r in retry_results if r.success]
                        new_received = BatchResultReconciler.collect_result_custom_ids(
                            successful_retry
                        )
                        missing_ids = missing_ids - new_received

                    for rid in missing_ids:
                        record_failure_counts[rid] = record_failure_counts.get(rid, 0) + 1

                if retry_attempts > 0 and missing_ids:
                    exhausted_recovery = self.build_exhausted_recovery(
                        missing_ids, record_failure_counts, retry_attempts
                    )

        # PHASE 2: VALIDATE — ensure all records meet validation conditions
        all_results = self.validate_and_reprompt(
            results=all_results,
            provider=provider,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            agent_config=agent_config,
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

    # =========================================================================
    # REPROMPT / VALIDATION OPERATIONS (delegated to reprompt_ops)
    # =========================================================================

    def validate_and_reprompt(
        self,
        results: list[BatchResult],
        provider: BaseBatchClient,
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str | None,
        agent_config: dict[str, Any] | None,
    ) -> list[BatchResult]:
        """Validate results and reprompt failures with feedback."""
        return _reprompt.validate_and_reprompt(
            action_indices=self._action_indices,
            dependency_configs=self._dependency_configs,
            storage_backend=self._storage_backend,
            results=results,
            provider=provider,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            agent_config=agent_config,
        )

    def validate_results(
        self,
        results: list[BatchResult],
        agent_config: dict[str, Any] | None,
    ) -> tuple[list[BatchResult], str | None]:
        """Validate results using configured UDF without resubmitting."""
        return _reprompt.validate_results(
            results=results,
            agent_config=agent_config,
        )

    def submit_reprompt_batch(
        self,
        provider: BaseBatchClient,
        failed_results: list[BatchResult],
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str | None,
        agent_config: dict[str, Any] | None,
        attempt: int,
    ) -> tuple[str, int] | None:
        """Submit a reprompt batch for failed validation records without blocking."""
        return _reprompt.submit_reprompt_batch(
            action_indices=self._action_indices,
            dependency_configs=self._dependency_configs,
            storage_backend=self._storage_backend,
            provider=provider,
            failed_results=failed_results,
            context_map=context_map,
            output_directory=output_directory,
            file_name=file_name,
            agent_config=agent_config,
            attempt=attempt,
        )

    def process_reprompt_results(
        self,
        reprompt_results: list[BatchResult],
        accumulated_results: list[BatchResult],
    ) -> list[BatchResult]:
        """Merge reprompt results into accumulated results (override by custom_id)."""
        return _reprompt.process_reprompt_results(
            reprompt_results=reprompt_results,
            accumulated_results=accumulated_results,
        )

    def apply_exhausted_reprompt_metadata(
        self,
        results: list[BatchResult],
        failed_ids: set[str],
        validation_name: str,
        attempt: int,
        on_exhausted: str,
    ) -> list[BatchResult]:
        """Apply reprompt exhaustion metadata to failed records."""
        return _reprompt.apply_exhausted_reprompt_metadata(
            results=results,
            failed_ids=failed_ids,
            validation_name=validation_name,
            attempt=attempt,
            on_exhausted=on_exhausted,
        )

    # =========================================================================
    # SERIALIZATION (delegated to retry_serialization)
    # =========================================================================

    @staticmethod
    def serialize_results(results: list[BatchResult]) -> list[dict[str, Any]]:
        """Serialize BatchResult objects for JSON persistence."""
        return serialize_results(results)

    @staticmethod
    def deserialize_results(data: list[dict[str, Any]]) -> list[BatchResult]:
        """Deserialize BatchResult objects from JSON."""
        return deserialize_results(data)
