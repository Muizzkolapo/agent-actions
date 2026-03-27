"""Shared result retrieval logic for batch services."""

import logging
from typing import Any

from agent_actions.llm.providers.batch_base import BaseBatchClient, BatchResult

logger = logging.getLogger(__name__)


def retrieve_and_reconcile(
    provider: BaseBatchClient,
    batch_id: str,
    output_directory: str | None,
    *,
    context_map: dict[str, Any] | None = None,
    record_count: int | None = None,
    file_name: str | None = None,
) -> list[BatchResult]:
    """Retrieve batch results from provider and log reconciliation."""
    from agent_actions.llm.batch.processing.reconciler import (
        BatchResultReconciler,
    )

    batch_results = provider.retrieve_results(batch_id, output_directory)

    # Log reconciliation
    expected = BatchResultReconciler.collect_expected_custom_ids(context_map or {})
    received = BatchResultReconciler.collect_result_custom_ids(batch_results)
    BatchResultReconciler.log_batch_reconciliation(
        batch_id=batch_id,
        expected_count=len(expected) or record_count or 0,
        received_count=len(received),
        file_name=file_name,
    )

    return batch_results
