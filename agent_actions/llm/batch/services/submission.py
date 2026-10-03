"""Batch submission service for task preparation and job submission."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_actions.errors import ConfigurationError, ConfigValidationError, ExternalServiceError
from agent_actions.llm.batch.core.batch_constants import BatchStatus, FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.core.batch_models import BatchJobEntry, SubmissionResult
from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
from agent_actions.llm.batch.infrastructure.context import (
    BatchContextManager,
    batch_output_name,
)
from agent_actions.llm.batch.infrastructure.registry import (
    BatchRegistryManager,
)
from agent_actions.llm.batch.processing.batch_passthrough_builder import (
    BatchPassthroughBuilder,
)
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers.local_batch_records import release_local_batch_record
from agent_actions.logging.core.manager import fire_event, get_manager
from agent_actions.logging.events import BatchSubmittedEvent
from agent_actions.logging.events.batch_events import (
    BatchStatusCheckFailedEvent,
    BatchSubmissionFailedEvent,
)
from agent_actions.output.response.config_schema import WhereClauseBehavior
from agent_actions.processing.result_collector import _safe_set_disposition
from agent_actions.storage.backend import DISPOSITION_DEFERRED, DISPOSITION_FILTERED

if TYPE_CHECKING:
    from agent_actions.processing.disposition_gate import DispositionGate

logger = logging.getLogger(__name__)


class BatchSubmissionService:
    """Service for submitting batch jobs.

    Handles task preparation, batch submission to providers, and registry management.
    """

    def __init__(
        self,
        task_preparator: BatchTaskPreparator,
        client_resolver: BatchClientResolver,
        context_manager: BatchContextManager,
        registry_manager_factory: Callable[[str], BatchRegistryManager],
        force_batch: bool = False,
        storage_backend: Any | None = None,
        disposition_gate: DispositionGate | None = None,
    ):
        """Initialize submission service with dependencies.

        Args:
            task_preparator: Preparator for batch tasks
            client_resolver: Resolver for batch API clients
            context_manager: Manager for batch context persistence
            registry_manager_factory: Factory function to create registry managers
            force_batch: Whether to force new batch submission
            storage_backend: Optional storage backend for disposition writes
            disposition_gate: Optional per-record idempotency gate for retry
        """
        self._task_preparator = task_preparator
        self._client_resolver = client_resolver
        self._context_manager = context_manager
        self._registry_manager_factory = registry_manager_factory
        self._force_batch = force_batch
        self._storage_backend = storage_backend
        self._disposition_gate = disposition_gate

    def prepare_batch_tasks(
        self,
        agent_config: dict[str, Any],
        data: list[dict[str, Any]],
        output_directory: str | None = None,
        batch_name: str | None = None,
        source_data: Any | None = None,
        workflow_metadata: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Prepare batch tasks from data.

        Args:
            agent_config: Agent configuration
            data: Input data to process
            output_directory: Output directory path
            batch_name: Name for the batch
            workflow_metadata: Optional workflow metadata for {{ workflow.* }} templates

        Returns:
            Tuple of (tasks, context_map)
        """
        provider = self._client_resolver.get_for_config(agent_config)
        prepared = self._task_preparator.prepare_tasks(
            agent_config=agent_config,
            data=data,
            provider=provider,
            output_directory=output_directory,
            batch_name=batch_name,
            source_data=source_data,
            workflow_metadata=workflow_metadata,
        )
        if prepared.stats.error_items:
            logger.warning(
                "Task preparation complete: %d tasks, %d filtered, %d skipped, "
                "%d failed (prep errors)",
                prepared.task_count,
                prepared.stats.total_filtered,
                prepared.stats.total_skipped,
                prepared.stats.error_items,
            )
        else:
            logger.debug(
                "Task preparation complete: %d tasks, %d filtered, %d skipped",
                prepared.task_count,
                prepared.stats.total_filtered,
                prepared.stats.total_skipped,
            )
        return prepared.tasks, prepared.context_map

    def check_status(
        self,
        batch_id: str,
        output_directory: str | None = None,
        action_name: str | None = None,
    ) -> BatchStatus:
        """Check the status of a batch job.

        Args:
            batch_id: ID of the batch job
            output_directory: Output directory for provider resolution
            action_name: Action name for registry lookup

        Returns:
            Current batch status

        Raises:
            ConfigurationError: If action_name is None
            ExternalServiceError: If status check fails
        """
        if action_name is None:
            raise ConfigurationError(
                "check_status requires action_name for registry lookup",
                context={"batch_id": batch_id},
            )
        provider = None
        try:
            manager = self._registry_manager_factory(action_name)
            provider = self._client_resolver.get_for_batch_id(batch_id, manager, output_directory)
            return provider.check_status(batch_id)  # type: ignore[return-value]
        except ConfigurationError:
            raise
        except Exception as e:
            vendor = (
                getattr(provider, "vendor_type", "unknown") if provider is not None else "unknown"
            )
            fire_event(
                BatchStatusCheckFailedEvent(
                    batch_id=batch_id,
                    provider=vendor,
                    error=str(e),
                )
            )
            raise ExternalServiceError(
                f"Failed to check batch status: {e}", context={"vendor": vendor}, cause=e
            ) from e

    def _carried_to_look_at_again(
        self,
        to_process: list[dict[str, Any]],
        carry_ids: set[str],
        action_name: str,
        batch_name: str,
    ) -> set[str]:
        """The inputs the gate carried that online would not simply carry.

        Two kinds. An input the guard filtered, which has no row by design: online's
        guard runs above its gate and judges it afresh every run, where the gate here
        would call it done for good. Sent on, the guard filters it again at no cost, or
        it now passes and is answered. And an input holding no stored row though its
        disposition says it should: finalize carries a row only for an input of the run,
        so one that left and returned has lost its row, and online re-queues it.
        """
        if not carry_ids or self._storage_backend is None:
            return set()
        filtered = carry_ids & {
            row["record_id"]
            for row in self._storage_backend.get_disposition(
                action_name, disposition=DISPOSITION_FILTERED
            )
        }
        holding = carry_ids - filtered
        if not holding:
            return filtered
        from agent_actions.processing.disposition_gate import build_carry_forward

        _found, missing = build_carry_forward(
            holding,
            action_name,
            batch_output_name(batch_name),
            self._storage_backend,
            produced_by=holding,
            rewriting={guid for record in to_process if (guid := record.get("source_guid"))},
        )
        return filtered | missing

    def submit_batch_job(
        self,
        agent_config: dict[str, Any],
        batch_name: str,
        data: list[dict[str, Any]],
        output_directory: str | None = None,
        force: bool = False,
        source_data: Any | None = None,
        workflow_metadata: dict[str, Any] | None = None,
        run_inputs: list[dict[str, Any]] | None = None,
        tombstone_path: str | None = None,
    ) -> SubmissionResult:
        """Submit a batch job, or return a passthrough when nothing is left to send.

        *run_inputs* is this action's input above every narrowing, recorded for
        carry-forward, which cannot otherwise tell a record the run left out from one
        that no longer exists. None records nothing, and neither does a repair.
        *tombstone_path* is the stored path the caller writes a tombstone passthrough
        to; the rows that file holds are merged in, or the write replaces them.
        """
        force_submission = force or self._force_batch
        if not batch_name:
            raise ConfigurationError(
                "batch_name is required for batch submission",
                context={"agent_config_keys": list(agent_config.keys())},
            )
        action_name = agent_config.get("action_name", batch_name)

        if not force_submission and output_directory:
            manager = self._registry_manager_factory(action_name)
            entry = manager.get_batch_job(batch_name)
            if entry and entry.is_in_flight:
                logger.info(
                    "Found existing in-flight batch job for %s: %s",
                    batch_name,
                    entry.batch_id,
                )
                logger.info(
                    "Skipping new batch submission. "
                    "Use --batch_continue to process completed batches."
                )
                return SubmissionResult(batch_id=entry.batch_id)
            # A finished job blocks resubmission while its results are still owed, so
            # the run collects them instead. Once collected it is no reason to skip:
            # the action is here because it has to run. FAILED/CANCELLED fall through.
            if entry and entry.status == BatchStatus.COMPLETED and entry.collected_at is None:
                logger.info(
                    "Found completed batch job for %s: %s — skipping resubmission",
                    batch_name,
                    entry.batch_id,
                )
                return SubmissionResult(batch_id=entry.batch_id)
        # Never off `data`: the record limit and the gate below both narrow it, and a
        # record either drops still holds rows this action must carry.
        run_input_guids = (
            [guid for row in run_inputs if (guid := row.get("source_guid"))]
            if run_inputs is not None
            else None
        )
        repairing = self._disposition_gate is not None and bool(self._disposition_gate.repairing)
        if repairing:
            # A repair answers what it named, and online carries every stored row it
            # did not name. Read against its inputs, a row under an identity this run
            # does not derive would be left out.
            run_input_guids = None
        carry_ids: set[str] = set()
        if self._disposition_gate is not None:
            to_process, carry_ids = self._disposition_gate.filter(data, action_name)
            again = self._carried_to_look_at_again(to_process, carry_ids, action_name, batch_name)
            carry_ids = carry_ids - again
            # Read off the input, so one looked at again keeps its place in it.
            data = (
                [record for record in data if record.get("source_guid") not in carry_ids]
                if again
                else to_process
            )

        if not data:
            logger.info(
                "All %d records have terminal dispositions — skipping batch submission",
                len(carry_ids),
            )
            return SubmissionResult(batch_id=None, passthrough={"carry_forward_only": True})

        tasks, context_map = self.prepare_batch_tasks(
            agent_config, data, output_directory, batch_name, source_data, workflow_metadata
        )

        if not tasks:
            return self._with_stored_rows(
                self._handle_empty_tasks(
                    agent_config, context_map, data, output_directory, action_name=action_name
                ),
                action_name,
                tombstone_path,
                run_input_guids,
            )

        if output_directory and self._storage_backend:
            self._context_manager.save_batch_context_map(
                self._storage_backend, action_name, context_map, batch_name
            )
            if repairing:
                # Not left to whoever started the repair: finalize would read an earlier
                # run's inputs as this one's.
                self._context_manager.clear_batch_inputs(
                    self._storage_backend, action_name, batch_name
                )
            elif run_input_guids is not None:
                self._context_manager.save_batch_inputs(
                    self._storage_backend, action_name, run_input_guids, batch_name
                )

        result = self._submit_to_provider(
            agent_config, batch_name, tasks, output_directory, action_name=action_name
        )

        if self._storage_backend and result.is_submitted:
            self._stamp_deferred(context_map, action_name, result.batch_id)

        return result

    def _with_stored_rows(
        self,
        result: SubmissionResult,
        action_name: str,
        tombstone_path: str | None,
        run_input_guids: list[str] | None,
    ) -> SubmissionResult:
        """Add the stored rows a tombstone does not replace, as finalize would.

        Nothing was left to send, so the passthrough is written as the whole of
        *tombstone_path*. Alone it replaces every answer stored there with nothing, and
        their dispositions still say done, so they are never answered again. The rows
        are read from that file and no other: a file in a subdirectory keeps its batch
        output under another name, and rows read from there would be stored twice.
        """
        passthrough = result.passthrough
        if (
            self._storage_backend is None
            or tombstone_path is None
            or not passthrough
            or passthrough.get("type") != "tombstone"
        ):
            return result
        from agent_actions.processing.disposition_gate import with_stored_rows_not_reproduced

        passthrough["data"] = with_stored_rows_not_reproduced(
            passthrough["data"],
            action_name,
            tombstone_path,
            self._storage_backend,
            batch_inputs=run_input_guids or (),
        )
        return result

    def _handle_empty_tasks(
        self,
        agent_config: dict[str, Any],
        context_map: dict[str, Any],
        data: list[dict[str, Any]],
        output_directory: str | None,
        action_name: str,
    ) -> SubmissionResult:
        """Handle case where no tasks remain after filtering.

        Args:
            agent_config: Agent configuration
            context_map: Context map from preparation
            data: Original input data
            output_directory: Output directory path
            action_name: Action name for passthrough records

        Returns:
            SubmissionResult with passthrough dict
        """
        has_failed_prep = any(
            BatchContextMetadata.get_filter_status(row) == FilterStatus.FAILED
            for row in context_map.values()
        )
        if has_failed_prep:
            passthrough = BatchPassthroughBuilder(
                output_directory, action_name=action_name
            ).from_context(context_map, reason="guard_skip")
            return SubmissionResult(passthrough=passthrough)

        has_guard_skipped = any(
            BatchContextMetadata.is_skipped(row) for row in context_map.values()
        )
        if has_guard_skipped:
            passthrough = BatchPassthroughBuilder(
                output_directory, action_name=action_name
            ).from_context(context_map, reason="guard_skip")
            return SubmissionResult(passthrough=passthrough)

        where_config = agent_config.get("where_clause") or {}
        behavior = WhereClauseBehavior(where_config.get("behavior", "filter"))

        if behavior == WhereClauseBehavior.FILTER:
            passthrough = {
                "type": "tombstone",
                "data": [],
                "output_directory": output_directory,
            }
        else:
            passthrough = BatchPassthroughBuilder(
                output_directory, action_name=action_name
            ).from_context(context_map, reason="where_clause_not_matched")
        return SubmissionResult(passthrough=passthrough)

    def _stamp_deferred(
        self,
        context_map: dict[str, Any],
        action_name: str,
        batch_id: str | None,
    ) -> None:
        """Stamp DISPOSITION_DEFERRED for all INCLUDED records after submission."""
        if not self._storage_backend:
            return
        for custom_id, entry in context_map.items():
            if BatchContextMetadata.get_filter_status(entry) != FilterStatus.INCLUDED:
                continue
            record_id = entry.get("source_guid") or custom_id
            _safe_set_disposition(
                self._storage_backend,
                action_name,
                record_id,
                DISPOSITION_DEFERRED,
                reason=f"batch_queued:batch_id={batch_id}",
            )

    def _submit_to_provider(
        self,
        agent_config: dict[str, Any],
        batch_name: str,
        tasks: list[dict[str, Any]],
        output_directory: str | None,
        action_name: str,
    ) -> SubmissionResult:
        """Submit batch to provider and save to registry.

        Args:
            agent_config: Agent configuration
            batch_name: Batch name
            tasks: Prepared tasks
            output_directory: Output directory path
            action_name: Action name for registry writes

        Returns:
            SubmissionResult with batch_id

        Raises:
            ConfigValidationError: If model_vendor missing
            ExternalServiceError: If submission fails
        """
        provider_type = agent_config.get("model_vendor")
        if not provider_type:
            raise ConfigValidationError(
                "model_vendor",
                "Missing required field 'model_vendor' for batch processing.",
            )
        provider_type = provider_type.lower()
        batch_id = "unknown"  # Initialize for error handling

        try:
            provider = self._client_resolver.get_for_config(agent_config)
            batch_id, initial_status = provider.submit_batch(tasks, batch_name, output_directory)

            get_manager().set_context(batch_id=batch_id)

            fire_event(
                BatchSubmittedEvent(
                    batch_id=batch_id,
                    action_name=action_name,
                    request_count=len(tasks),
                    provider=provider_type,
                )
            )

            if output_directory:
                registry_name = action_name
                manager = self._registry_manager_factory(registry_name)
                file_key = batch_name
                entry = BatchJobEntry(
                    batch_id=batch_id,
                    status=initial_status,
                    timestamp=datetime.now(UTC).isoformat(),
                    provider=provider_type,
                    record_count=len(tasks),
                    workflow_session_id=agent_config.get("workflow_session_id"),
                    file_name=file_key,
                    is_versioned_agent=agent_config.get("is_versioned_agent"),
                    version_base_name=agent_config.get("version_base_name"),
                )
                # A FAILED or CANCELLED entry falls through the resubmission
                # guard and is overwritten here; the batch it named stops being
                # reachable at that moment.
                superseded = manager.batch_id_at(file_key)
                manager.save_batch_job(file_key, entry)
                # After the save, never before: the successor has to be recorded
                # before anything is thrown away, or a crash in between leaves a
                # batch this run paid for named by nothing.
                if superseded and superseded != batch_id:
                    release_local_batch_record(superseded)

            return SubmissionResult(batch_id=batch_id)

        except ConfigValidationError:
            raise
        except Exception as e:
            fire_event(
                BatchSubmissionFailedEvent(
                    batch_id=batch_id,
                    provider=provider_type,
                    error=str(e),
                )
            )
            raise ExternalServiceError(
                f"Failed to submit batch job: {e}", context={"vendor": provider_type}, cause=e
            ) from e
