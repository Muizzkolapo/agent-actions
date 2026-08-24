"""Consolidated reprompt exhaustion handling.

Single source of truth for what happens when reprompt recovery attempts
are exhausted. Optionally raises based on the ``on_exhausted`` policy
configured in the workflow.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_actions.llm.providers.batch_base import BatchResult

from agent_actions.errors import exhaustion_halt
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.validation_events import RepromptValidationFailedEvent
from agent_actions.processing.types import RecoveryMetadata, RepromptMetadata

logger = logging.getLogger(__name__)


def apply_exhausted_reprompt(
    results: list[BatchResult],
    failed_ids: set[str],
    validation_name: str,
    attempt: int,
    on_exhausted: str,
    per_record_attempts: dict[str, int] | None = None,
    failure_type_counts: dict[str, dict[str, int]] | None = None,
) -> Exception | None:
    """Apply reprompt exhaustion metadata to records that failed validation.

    Mutates results in-place and hands back the halt `on_exhausted: raise` wants
    thrown, or None. It is handed back rather than thrown because batch writes
    its output file once at the end: throwing here would discard every record in
    it the reprompt rounds had already graduated.

    Args:
        results: Batch results (mutated in-place for failed IDs).
        failed_ids: Custom IDs that still fail validation.
        validation_name: Name of the validation strategy.
        attempt: Default number of attempts (used when per_record_attempts
            is not provided or a record is missing from it).
        on_exhausted: ``"return_last"`` to accept last response, or
            ``"raise"`` to propagate a RuntimeError.
        per_record_attempts: Optional per-record attempt counts. When
            provided, each record's metadata uses its own count instead
            of the scalar ``attempt``. Used by the sync reprompt path.
        failure_type_counts: Optional per-record failure type counts.
            Maps custom_id → ``{"parse_error": N, "udf_fail": M, ...}``.
            When provided, populates ``parse_error_count``,
            ``schema_fail_count``, ``udf_fail_count`` on RepromptMetadata.

    Returns:
        The halt to raise once the output is written, or None.
    """
    if failed_ids:
        fire_event(
            RepromptValidationFailedEvent(
                action_name="batch",
                attempt=attempt,
                error=f"Validation '{validation_name}' exhausted for {len(failed_ids)} records",
            )
        )

    pending: Exception | None = None
    for result in results:
        if result.custom_id not in failed_ids:
            continue

        if on_exhausted == "raise" and pending is None:
            pending = exhaustion_halt(
                f"Reprompt validation exhausted for {result.custom_id} "
                f"after {attempt} attempts (validation: {validation_name})"
            )

        record_attempts = (
            per_record_attempts.get(result.custom_id, attempt) if per_record_attempts else attempt
        )

        counts = (failure_type_counts or {}).get(result.custom_id, {})

        if not result.recovery_metadata:
            result.recovery_metadata = RecoveryMetadata()

        result.recovery_metadata.reprompt = RepromptMetadata(
            attempts=record_attempts,
            passed=False,
            validation=validation_name,
            parse_error_count=counts.get("parse_error", 0),
            schema_fail_count=counts.get("schema_fail", 0),
            udf_fail_count=counts.get("udf_fail", 0),
        )

    return pending
