"""Cascade-blocking record filter for processing strategies.

Partitions input records into processable (ACTIVE) and quarantined
(CASCADE_BLOCKING) sets before any strategy-specific logic runs.
Quarantined records produce UNPROCESSED results immediately — no LLM
call, no tool invocation, no compute wasted.

Every processing strategy must call :func:`partition_cascade_records`
at the top of its ``invoke()`` method.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_actions.processing.record_helpers import build_tombstone
from agent_actions.processing.types import ProcessingResult
from agent_actions.record.reasons import UPSTREAM_UNPROCESSED
from agent_actions.record.state import CASCADE_BLOCKING_VALUES

logger = logging.getLogger(__name__)

CASCADE_QUARANTINE_REASON = "cascade_quarantine"


def partition_cascade_records(
    records: list[dict[str, Any]],
    *,
    action_name: str,
) -> tuple[list[dict[str, Any]], list[ProcessingResult]]:
    """Split records into (processable, quarantined_results).

    Records whose ``_state`` is in :data:`CASCADE_BLOCKING_VALUES`
    (``cascade_skipped``, ``failed``, ``exhausted``) are converted to
    :class:`ProcessingResult.unprocessed` immediately.  All other records
    are returned for normal processing.

    Args:
        records: Input records (may include cascade-blocking records).
        action_name: Current action name (for tombstone construction).

    Returns:
        Tuple of (processable_records, quarantined_results).
        processable_records preserves original ordering.
        quarantined_results are ready to merge into the strategy's output.
    """
    processable: list[dict[str, Any]] = []
    quarantined: list[ProcessingResult] = []

    for record in records:
        state = record.get("_state") if isinstance(record, dict) else None
        if state in CASCADE_BLOCKING_VALUES:
            source_guid = record.get("source_guid") if isinstance(record, dict) else None
            tombstone = build_tombstone(
                action_name,
                record,
                UPSTREAM_UNPROCESSED,
                source_guid=source_guid,
            )
            quarantined.append(
                ProcessingResult.unprocessed(
                    data=[tombstone],
                    reason=UPSTREAM_UNPROCESSED,
                    source_guid=source_guid,
                    input_record=record,
                )
            )
            logger.info(
                "Quarantining record %s at action '%s': upstream %s",
                source_guid or "?",
                action_name,
                state,
            )
        else:
            processable.append(record)

    if quarantined:
        logger.info(
            "Action '%s': %d record(s) quarantined, %d processable",
            action_name,
            len(quarantined),
            len(processable),
        )

    return processable, quarantined
