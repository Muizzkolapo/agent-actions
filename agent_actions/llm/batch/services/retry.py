"""Batch retry service for missing record recovery and reprompt validation."""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile  # noqa: F401
from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult
from agent_actions.processing.types import RecoveryMetadata, RetryMetadata
from agent_actions.utils.module_loader import load_module_from_path

# Re-export: tests patch retry.wait_for_batch_completion
from .retry_legacy import wait_for_batch_completion  # noqa: F401

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


class BatchRetryService:
    """Handles retry and reprompt logic for batch processing."""

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
    # LEGACY BLOCKING METHODS (deprecated — delegated to retry_legacy)
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

        DEPRECATED: Delegates to retry_legacy. Use async recovery path instead.
        """
        from .retry_legacy import retrieve_results_with_retry as _legacy

        return _legacy(
            self,
            provider,
            batch_id,
            output_directory,
            context_map=context_map,
            record_count=record_count,
            file_name=file_name,
            agent_config=agent_config,
        )

    def _resubmit_missing_records(
        self,
        provider: BaseBatchClient,
        missing_ids: set[str],
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str | None,
        agent_config: dict[str, Any] | None,
    ) -> list[BatchResult]:
        """Resubmit missing records as a new batch and wait for completion.

        DEPRECATED: Delegates to retry_legacy. Use submit_retry_batch() instead.
        """
        from .retry_legacy import _resubmit_missing_records as _legacy

        return _legacy(
            self,
            provider,
            missing_ids,
            context_map,
            output_directory,
            file_name,
            agent_config,
        )

    def validate_and_reprompt(
        self,
        results: list[BatchResult],
        provider: BaseBatchClient,
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str | None,
        agent_config: dict[str, Any] | None,
        action_indices: dict[str, int] | None = None,
        dependency_configs: dict[str, dict] | None = None,
    ) -> list[BatchResult]:
        """Validate results and reprompt failures with feedback.

        DEPRECATED: Delegates to retry_legacy. Use validate_results() +
        submit_reprompt_batch() for non-blocking flow.
        """
        from .retry_legacy import validate_and_reprompt as _legacy

        return _legacy(
            self,
            results,
            provider,
            context_map,
            output_directory,
            file_name,
            agent_config,
            action_indices,
            dependency_configs,
        )

    # =========================================================================
    # NON-BLOCKING ASYNC METHODS (#942)
    # =========================================================================

    def submit_retry_batch(
        self,
        provider: BaseBatchClient,
        missing_ids: set[str],
        context_map: dict[str, Any],
        output_directory: str,
        file_name: str | None,
        agent_config: dict[str, Any] | None,
    ) -> tuple[str, int] | None:
        """Submit a retry batch for missing records without blocking.

        Unlike _resubmit_missing_records, this returns immediately after
        submission — no polling/waiting.

        Args:
            provider: Batch API client
            missing_ids: Set of custom_ids that are missing
            context_map: Context map with original record data
            output_directory: Output directory path
            file_name: Original file name
            agent_config: Agent configuration

        Returns:
            Tuple of (batch_id, record_count) if submitted, None if nothing to submit
        """
        from agent_actions.llm.batch.processing.preparator import (
            BatchTaskPreparator,
        )

        missing_records = []
        for custom_id in missing_ids:
            if custom_id in context_map:
                record = context_map[custom_id].copy()
                if "target_id" not in record:
                    record["target_id"] = custom_id
                missing_records.append(record)

        if not missing_records:
            logger.warning("No records found in context_map for missing IDs")
            return None

        try:
            batch_name = f"{file_name}_retry" if file_name else "retry"
            preparator = BatchTaskPreparator(storage_backend=self._storage_backend)
            prepared = preparator.prepare_tasks(
                agent_config=agent_config or {},
                data=missing_records,
                provider=provider,
                output_directory=output_directory,
                batch_name=batch_name,
            )

            if not prepared.tasks:
                logger.warning("No tasks prepared for retry batch")
                return None

            retry_batch_id, _ = provider.submit_batch(
                tasks=prepared.tasks,
                batch_name=batch_name,
                output_directory=output_directory,
            )
            logger.info(
                "Async retry batch submitted: %s with %d records",
                retry_batch_id,
                len(prepared.tasks),
            )
            return (retry_batch_id, len(prepared.tasks))

        except Exception as e:
            logger.warning("Failed to submit retry batch: %s", e, exc_info=True)
            return None

    def process_retry_results(
        self,
        results: list[BatchResult],
        accumulated_results: list[BatchResult],
        context_map: dict[str, Any],
        record_failure_counts: dict[str, int],
        missing_ids: set[str],
    ) -> tuple[list[BatchResult], set[str], dict[str, int], dict[str, RecoveryMetadata] | None]:
        """Process retry batch results and determine if more retries are needed.

        Args:
            results: Results from the retry batch
            accumulated_results: Previously accumulated results
            context_map: Context map for expected ID checking
            record_failure_counts: Per-record failure counts
            missing_ids: IDs that were missing before this retry

        Returns:
            Tuple of (merged_results, still_missing_ids, updated_failure_counts, exhausted_recovery)
            exhausted_recovery is non-None only if retries are exhausted.
        """
        all_results = list(accumulated_results)

        if results:
            for res in results:
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

            all_results.extend(results)

            successful_retry = [r for r in results if r.success]
            new_received = BatchResultReconciler.collect_result_custom_ids(successful_retry)
            missing_ids = missing_ids - new_received

        updated_counts = dict(record_failure_counts)
        for rid in missing_ids:
            updated_counts[rid] = updated_counts.get(rid, 0) + 1

        return all_results, missing_ids, updated_counts, None

    def build_exhausted_recovery(
        self, missing_ids: set[str], record_failure_counts: dict[str, int]
    ) -> dict[str, RecoveryMetadata]:
        """Build recovery metadata for records that exhausted all retry attempts.

        Args:
            missing_ids: IDs still missing after all retries
            record_failure_counts: Per-record failure counts

        Returns:
            Dict mapping custom_id -> RecoveryMetadata for exhausted records
        """
        exhausted_recovery: dict[str, RecoveryMetadata] = {}
        for rid in missing_ids:
            failures = record_failure_counts.get(rid, 1)
            exhausted_recovery[rid] = RecoveryMetadata(
                retry=RetryMetadata(
                    attempts=failures,
                    failures=failures,
                    succeeded=False,
                    reason="missing",
                    timestamp=datetime.now(UTC).isoformat(),
                )
            )
        logger.warning(
            "Batch retry exhausted: %d records still missing",
            len(missing_ids),
        )
        return exhausted_recovery

    def validate_results(
        self,
        results: list[BatchResult],
        agent_config: dict[str, Any] | None,
    ) -> tuple[list[BatchResult], str | None]:
        """Validate results using configured UDF without resubmitting.

        Args:
            results: Batch results to validate
            agent_config: Agent configuration with reprompt settings

        Returns:
            Tuple of (failed_results, validation_name).
            Empty failed_results means all passed.
            None validation_name means reprompt is not configured.
        """
        reprompt_config = (agent_config or {}).get("reprompt")
        if not reprompt_config:
            return [], None

        validation_name = reprompt_config.get("validation")
        if not validation_name:
            return [], None

        from agent_actions.processing.recovery.validation import get_validation_function
        from agent_actions.utils.tools_resolver import resolve_tools_path

        validation_path = reprompt_config.get("validation_path")
        if not validation_path:
            validation_path = resolve_tools_path(agent_config or {})

        validation_module = reprompt_config.get("validation_module", "reprompt_validations")

        if validation_path:
            _import_validation_module(validation_module, validation_path)
        else:
            _import_validation_module(validation_module, None)

        try:
            validation_func, _ = get_validation_function(validation_name)
        except ValueError as e:
            logger.error("Failed to get validation function: %s", e)
            return [], None

        failed_results = []
        for result in results:
            if not result.success:
                continue

            if (
                result.recovery_metadata
                and result.recovery_metadata.reprompt
                and result.recovery_metadata.reprompt.passed
            ):
                continue

            try:
                is_valid = validation_func(result.content)
            except Exception:
                # UDF raised at runtime — could be a code bug or unexpected LLM output.
                # Treat as validation failure so the batch can reprompt rather than abort.
                logger.exception(
                    "Validation UDF raised an exception for record %s (treating as failure)",
                    result.custom_id,
                )
                is_valid = False

            if not is_valid:
                failed_results.append(result)

        if not failed_results:
            logger.info("All %d results passed validation", len(results))

        return failed_results, validation_name

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
        """Submit a reprompt batch for failed validation records without blocking.

        Args:
            provider: Batch API client
            failed_results: Results that failed validation
            context_map: Context map for record lookup
            output_directory: Output directory path
            file_name: Original file name
            agent_config: Agent configuration
            attempt: Current reprompt attempt number

        Returns:
            Tuple of (batch_id, record_count) if submitted, None if nothing to submit
        """
        from agent_actions.llm.batch.processing.preparator import (
            BatchTaskPreparator,
        )
        from agent_actions.processing.recovery.response_validator import build_validation_feedback
        from agent_actions.processing.recovery.validation import get_validation_function

        reprompt_config = (agent_config or {}).get("reprompt", {})
        validation_name = reprompt_config.get("validation")
        if not validation_name:
            return None

        try:
            _, feedback_message = get_validation_function(validation_name)
        except ValueError as e:
            logger.error("Failed to get validation function for reprompt: %s", e)
            return None

        reprompt_records = []
        for failed_result in failed_results:
            custom_id = failed_result.custom_id
            if custom_id not in context_map:
                logger.warning("Cannot reprompt %s: not found in context_map", custom_id)
                continue

            original_record = context_map[custom_id].copy()

            feedback = build_validation_feedback(
                failed_response=failed_result.content,
                feedback_message=feedback_message,
            )

            original_user_content = original_record.get("user_content", "")
            original_record["user_content"] = f"{original_user_content}\n\n{feedback}"

            if "target_id" not in original_record:
                original_record["target_id"] = custom_id

            reprompt_records.append(original_record)

        if not reprompt_records:
            logger.warning("No records to reprompt")
            return None

        try:
            reprompt_batch_name = f"{file_name or 'batch'}_reprompt_{attempt}"
            preparator = BatchTaskPreparator(
                action_indices=self._action_indices,
                dependency_configs=self._dependency_configs,
                storage_backend=self._storage_backend,
            )
            prepared = preparator.prepare_tasks(
                agent_config=agent_config or {},
                data=reprompt_records,
                provider=provider,
                output_directory=output_directory,
                batch_name=reprompt_batch_name,
            )

            batch_id, _ = provider.submit_batch(
                tasks=prepared.tasks,
                batch_name=reprompt_batch_name,
                output_directory=output_directory,
            )

            logger.info(
                "Async reprompt batch submitted: %s with %d records (attempt %d)",
                batch_id,
                len(prepared.tasks),
                attempt,
            )
            return (batch_id, len(prepared.tasks))

        except Exception as e:
            logger.exception("Error submitting reprompt batch: %s", e)
            return None

    def process_reprompt_results(
        self,
        reprompt_results: list[BatchResult],
        accumulated_results: list[BatchResult],
    ) -> list[BatchResult]:
        """Merge reprompt results into accumulated results (override by custom_id).

        Args:
            reprompt_results: New results from reprompt batch
            accumulated_results: Previously accumulated results

        Returns:
            Merged results with reprompt results replacing originals by custom_id
        """
        result_map = {r.custom_id: r for r in accumulated_results}

        for reprompt_result in reprompt_results:
            if reprompt_result.custom_id in result_map:
                existing_recovery = result_map[reprompt_result.custom_id].recovery_metadata
                if not reprompt_result.recovery_metadata:
                    reprompt_result.recovery_metadata = RecoveryMetadata()
                if existing_recovery and existing_recovery.retry:
                    reprompt_result.recovery_metadata.retry = existing_recovery.retry

            result_map[reprompt_result.custom_id] = reprompt_result

        return list(result_map.values())

    def apply_exhausted_reprompt_metadata(
        self,
        results: list[BatchResult],
        failed_ids: set[str],
        validation_name: str,
        attempt: int,
        on_exhausted: str,
    ) -> list[BatchResult]:
        """Apply reprompt exhaustion metadata to failed records.

        Mutates results in-place (sets recovery_metadata on individual items)
        and returns the same list for convenience.

        Args:
            results: All accumulated results (mutated in-place)
            failed_ids: IDs that still fail validation
            validation_name: Name of the validation UDF
            attempt: Number of attempts made
            on_exhausted: Policy — "return_last" or "raise"

        Returns:
            The same results list with exhaustion metadata applied

        Raises:
            RuntimeError: If on_exhausted == "raise"
        """
        from agent_actions.processing.types import RepromptMetadata

        for result in results:
            if result.custom_id not in failed_ids:
                continue

            if on_exhausted == "raise":
                raise RuntimeError(
                    f"Reprompt validation exhausted for {result.custom_id} "
                    f"after {attempt} attempts (validation: {validation_name})"
                )

            if not result.recovery_metadata:
                result.recovery_metadata = RecoveryMetadata()

            result.recovery_metadata.reprompt = RepromptMetadata(
                attempts=attempt,
                passed=False,
                validation=validation_name,
            )

        return results

    @staticmethod
    def serialize_results(results: list[BatchResult]) -> list[dict[str, Any]]:
        """Serialize BatchResult objects for JSON persistence.

        Args:
            results: Batch results to serialize

        Returns:
            List of dicts suitable for JSON serialization
        """
        serialized = []
        for r in results:
            d: dict[str, Any] = {
                "custom_id": r.custom_id,
                "content": r.content,
                "success": r.success,
            }
            if r.metadata:
                d["metadata"] = r.metadata
            if r.recovery_metadata:
                d["recovery_metadata"] = r.recovery_metadata.to_dict()
            serialized.append(d)
        return serialized

    @staticmethod
    def deserialize_results(data: list[dict[str, Any]]) -> list[BatchResult]:
        """Deserialize BatchResult objects from JSON.

        Args:
            data: List of dicts from JSON

        Returns:
            List of BatchResult objects
        """
        results = []
        for d in data:
            recovery = None
            if d.get("recovery_metadata"):
                from agent_actions.processing.types import RepromptMetadata

                rm = d["recovery_metadata"]
                retry = None
                reprompt = None
                if rm.get("retry"):
                    retry = RetryMetadata(**rm["retry"])
                if rm.get("reprompt"):
                    reprompt = RepromptMetadata(**rm["reprompt"])
                recovery = RecoveryMetadata(retry=retry, reprompt=reprompt)

            result = BatchResult(
                custom_id=d["custom_id"],
                content=d["content"],
                success=d["success"],
                metadata=d.get("metadata"),
            )
            result.recovery_metadata = recovery
            results.append(result)
        return results


def _import_validation_module(validation_module: str, validation_path: str | None) -> None:
    """Import validation module to register UDFs via decorators.

    Args:
        validation_module: Name of the Python module (without .py extension)
        validation_path: Path where the module is located (or None for PYTHONPATH)
    """
    try:
        module = load_module_from_path(
            module_name=validation_module,
            module_path=validation_path,
            execute=True,
            fallback_import=True,
            cache=True,
        )

        if module:
            logger.debug("Successfully imported validation module: %s", validation_module)
        else:
            logger.warning(
                "Could not import validation module '%s'. "
                "Ensure the module exists and validation_path is configured correctly.",
                validation_module,
            )
    except ImportError as e:
        from agent_actions.errors import ConfigurationError

        raise ConfigurationError(
            f"Cannot import validation module '{validation_module}': {e}",
            context={"validation_module": validation_module, "validation_path": validation_path},
            cause=e,
        ) from e
    except Exception as e:
        logger.warning("Failed to import validation module '%s': %s", validation_module, e)
