"""Reconciliation of batch request IDs to batch responses."""

import logging
from dataclasses import dataclass
from typing import Any

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata

logger = logging.getLogger(__name__)


@dataclass
class BatchReconciliationResult:
    """Result of reconciling batch results with expected records."""

    processed_ids: set[str]
    missing_ids: set[str]
    passthrough_records: list[tuple[str, dict[str, Any]]]


class BatchResultReconciler:
    """Reconciles batch results with expected records from context map."""

    def __init__(self, context_map: dict[str, Any]):
        """Initialize reconciler with context map."""
        self.context_map = context_map or {}
        self._processed_ids: set[str] = set()

    def mark_processed(self, custom_id: Any) -> None:
        """Mark a custom_id as processed."""
        if custom_id is not None:
            self._processed_ids.add(str(custom_id))

    def get_expected_ids(self) -> set[str]:
        """Get custom_ids expected in batch results (status='included' only)."""
        return self.collect_expected_custom_ids(self.context_map)

    def get_missing_ids(self) -> set[str]:
        """Get custom_ids that were expected but not processed."""
        expected_ids = self.get_expected_ids()
        missing_ids = expected_ids - self._processed_ids
        return missing_ids

    def get_passthrough_records(self) -> list[tuple[str, dict[str, Any]]]:
        """Get records needing passthrough (skipped or missing, excluding filtered)."""
        passthrough_records = []

        for custom_id, original_row in self.context_map.items():
            if str(custom_id) in self._processed_ids:
                continue

            filter_status = BatchContextMetadata.get_filter_status(original_row)

            if filter_status == FilterStatus.FILTERED:
                continue

            if filter_status in (FilterStatus.SKIPPED, FilterStatus.INCLUDED, None):
                passthrough_records.append((custom_id, original_row))

        return passthrough_records

    def reconcile(self) -> BatchReconciliationResult:
        """Perform full reconciliation of processed, missing, and passthrough records."""
        missing_ids = self.get_missing_ids()

        if missing_ids:
            logger.info(
                "Missing %d records in batch results. Continuing with available data.",
                len(missing_ids),
            )
            logger.debug("Missing custom_ids: %s", sorted(missing_ids))

        passthrough_records = self.get_passthrough_records()

        return BatchReconciliationResult(
            processed_ids=self._processed_ids.copy(),
            missing_ids=missing_ids,
            passthrough_records=passthrough_records,
        )

    def get_record_by_id(self, custom_id: str) -> dict[str, Any]:
        """Get original record data by custom_id, or empty dict if not found."""
        return self.context_map.get(str(custom_id), {})  # type: ignore[no-any-return]

    def get_source_guid(self, custom_id: str, fallback: str | None = None) -> str:
        """Get source_guid for a custom_id, falling back to custom_id itself."""
        original_row = self.get_record_by_id(custom_id)
        return original_row.get("source_guid", fallback or custom_id)  # type: ignore[no-any-return]

    def get_record_index(self, custom_id: str) -> int:
        """Get the index of a custom_id in context_map order, or -1 if not found."""
        context_keys = list(self.context_map.keys())
        try:
            return context_keys.index(str(custom_id))
        except ValueError:
            return -1

    @staticmethod
    def collect_expected_custom_ids(context_map: dict[str, Any]) -> set:
        """Collect custom_ids of records submitted to batch API (status='included' only)."""
        return {
            str(custom_id)
            for custom_id, original_row in (context_map or {}).items()
            if BatchContextMetadata.is_included(original_row)
            or BatchContextMetadata.get_filter_status(original_row) is None
        }

    @staticmethod
    def collect_result_custom_ids(batch_results: list[Any]) -> set:
        """Collect custom_ids from batch results, ignoring error_line_* placeholders."""
        result_ids: set = set()
        for batch_result in batch_results or []:
            custom_id = getattr(batch_result, "custom_id", None)
            if not custom_id:
                continue
            custom_id_str = str(custom_id)
            if custom_id_str.startswith("error_line_"):
                continue
            result_ids.add(custom_id_str)
        return result_ids

    @staticmethod
    def log_batch_reconciliation(
        *, batch_id: str, expected_count: int, received_count: int, file_name: str | None = None
    ) -> None:
        """Log batch reconciliation status (expected vs received counts)."""
        if expected_count == 0:
            return

        label = file_name or batch_id
        if expected_count == received_count:
            logger.info(
                "Batch reconciliation for %s: expected %d result(s), received %d",
                label,
                expected_count,
                received_count,
            )
        else:
            logger.warning(
                "Batch reconciliation for %s: expected %d result(s), received %d",
                label,
                expected_count,
                received_count,
            )
