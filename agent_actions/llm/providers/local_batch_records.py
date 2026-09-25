"""Reclaiming what a provider records about a batch inside the user's project."""

import logging

from agent_actions.config.paths import PathManagerError

logger = logging.getLogger(__name__)


def release_local_batch_record(batch_id: str) -> None:
    """Drop what a provider recorded in the project about one batch.

    Called where a batch id stops being named by the registry, never when its
    results are read: the caller still has to write and reconcile them, and a
    failure there brings the next run back for the same batch.

    Only the agac provider records one here; other vendors' ids pass through.
    Failing to reclaim is reported, never raised — every caller is mid-way
    through work that already succeeded.
    """
    from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

    try:
        AgacBatchClient.release_batch(batch_id)
    except (OSError, PathManagerError) as e:
        logger.warning("Could not reclaim the local record for batch %s: %s", batch_id, e)


def discard_partial_batch_records() -> None:
    """Drop the half-written records an interrupted write left behind.

    One written before its registry entry was saved is named by nothing, so no
    per-batch release can reach it. Safe to sweep whole where records are not,
    because a `.tmp` belongs to no workflow — except one a write is still
    holding, which age tells apart.
    """
    from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

    try:
        AgacBatchClient.discard_partial_writes()
    except (OSError, PathManagerError) as e:
        logger.warning("Could not reclaim half-written batch records: %s", e)
