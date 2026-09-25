"""Reclaiming what a provider records about a batch inside the user's project."""

import logging

logger = logging.getLogger(__name__)


def release_local_batch_record(batch_id: str) -> None:
    """Drop what a provider recorded in the project about one batch.

    Called where a batch id stops being named by the registry — nothing can be
    sent back to it, so the payload it was submitted with has nothing left to
    say. Never when results are read: the caller still has to write, parse and
    reconcile them, and a failure there brings the next run back for the batch.

    Only the agac provider records a batch in the project; every other keeps its
    copy at the vendor, so their batch ids name nothing here and pass through.
    """
    from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

    AgacBatchClient.release_batch(batch_id)


def discard_partial_batch_records() -> None:
    """Drop every half-written record in the project.

    An atomic write killed between create and rename leaves a `.tmp` holding the
    same payload, and one written before the registry entry was saved is named
    by nothing — no per-batch release can reach it. Sweeping them all is safe
    where sweeping records is not: a `.tmp` is never a live record, so this
    cannot take a batch another workflow is still waiting on.
    """
    from agent_actions.llm.providers.agac.batch_client import AgacBatchClient

    AgacBatchClient.discard_partial_writes()
