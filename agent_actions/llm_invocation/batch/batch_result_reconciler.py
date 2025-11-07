"""
Result Reconciler.

Handles matching of batch request IDs to batch responses, identifying missing
records, and determining which records need passthrough treatment.
"""

import logging
from typing import Dict, Set, List, Any, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BatchReconciliationResult:
    """
    Result of reconciling batch results with expected records.

    Attributes:
        processed_ids: Set of custom_ids that were successfully processed
        missing_ids: Set of custom_ids that were expected but not processed
        passthrough_records: List of (custom_id, original_row) tuples that need passthrough
    """
    processed_ids: Set[str]
    missing_ids: Set[str]
    passthrough_records: List[Tuple[str, Dict[str, Any]]]


class BatchResultReconciler:
    """
    Reconciles batch results with expected records from context map.

    This class handles the complex logic of:
    1. Tracking which records were processed
    2. Identifying missing records (expected but not received)
    3. Determining which records need passthrough treatment based on filter status

    Example:
        reconciler = ResultReconciler(context_map)

        # Track processed IDs as you process batch results
        for batch_result in batch_results:
            reconciler.mark_processed(batch_result.custom_id)

        # Get reconciliation result
        result = reconciler.reconcile()

        # Handle missing records
        if result.missing_ids:
            logger.warning(f"Missing {len(result.missing_ids)} records")

        # Create passthrough for unprocessed records
        for custom_id, original_row in result.passthrough_records:
            # Create passthrough item...
    """

    def __init__(self, context_map: Dict[str, Any]):
        """
        Initialize reconciler with context map.

        Args:
            context_map: Map of custom_id -> original row data
                        Must include '_batch_filter_status' field
        """
        self.context_map = context_map or {}
        self._processed_ids: Set[str] = set()

    def mark_processed(self, custom_id: Any) -> None:
        """
        Mark a custom_id as processed.

        Args:
            custom_id: The custom ID that was processed (will be converted to string)
        """
        if custom_id is not None:
            self._processed_ids.add(str(custom_id))

    def get_expected_ids(self) -> Set[str]:
        """
        Get set of custom_ids that are expected to be processed.

        Only includes records with _batch_filter_status='included'.
        Skipped and filtered records are not expected in batch results.

        Returns:
            Set of custom_ids (as strings) that should be in batch results
        """
        expected_ids = {
            str(custom_id)
            for custom_id, original_row in self.context_map.items()
            if original_row.get('_batch_filter_status', 'included') == 'included'
        }
        return expected_ids

    def get_missing_ids(self) -> Set[str]:
        """
        Get set of custom_ids that were expected but not processed.

        Returns:
            Set of custom_ids that are missing from results
        """
        expected_ids = self.get_expected_ids()
        missing_ids = expected_ids - self._processed_ids
        return missing_ids

    def get_passthrough_records(self) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Get records that need passthrough treatment.

        Passthrough records include:
        1. Records with _batch_filter_status='skipped' (always passthrough)
        2. Records with _batch_filter_status='included' that weren't processed (missing)

        Excluded:
        - Records that were already processed
        - Records with _batch_filter_status='filtered'

        Returns:
            List of (custom_id, original_row) tuples that need passthrough
        """
        passthrough_records = []

        for custom_id, original_row in self.context_map.items():
            # Skip records that were already processed
            if custom_id in self._processed_ids:
                continue

            filter_status = original_row.get('_batch_filter_status', 'included')

            # Skip filtered records (they should not appear in output)
            if filter_status == 'filtered':
                continue

            # Include skipped and included (but missing) records
            if filter_status in ['skipped', 'included']:
                passthrough_records.append((custom_id, original_row))

        return passthrough_records

    def reconcile(self) -> BatchReconciliationResult:
        """
        Perform full reconciliation.

        This method combines all reconciliation logic into a single call,
        providing a complete picture of processing status.

        Returns:
            BatchReconciliationResult containing processed, missing, and passthrough records
        """
        missing_ids = self.get_missing_ids()

        # Log warning if records are missing
        if missing_ids:
            logger.info(
                "Missing %d records in batch results. Continuing with available data.",
                len(missing_ids)
            )
            logger.debug("Missing custom_ids: %s", sorted(missing_ids))

        passthrough_records = self.get_passthrough_records()

        return BatchReconciliationResult(
            processed_ids=self._processed_ids.copy(),
            missing_ids=missing_ids,
            passthrough_records=passthrough_records
        )

    def get_record_by_id(self, custom_id: str) -> Dict[str, Any]:
        """
        Get original record data by custom_id.

        Args:
            custom_id: The custom ID to look up

        Returns:
            Original row data, or empty dict if not found
        """
        return self.context_map.get(custom_id, {})

    def get_source_guid(self, custom_id: str, fallback: str = None) -> str:
        """
        Get source_guid for a custom_id with fallback.

        Args:
            custom_id: The custom ID to look up
            fallback: Value to return if source_guid not found (defaults to custom_id)

        Returns:
            Source GUID for the record
        """
        original_row = self.get_record_by_id(custom_id)
        return original_row.get('source_guid', fallback or custom_id)

    def get_record_index(self, custom_id: str) -> int:
        """
        Get the index of a custom_id in the context_map order.

        Useful for loop correlation ID generation where index matters.

        Args:
            custom_id: The custom ID to find

        Returns:
            Index of the custom_id in context_map keys, or -1 if not found
        """
        context_keys = list(self.context_map.keys())
        try:
            return context_keys.index(custom_id)
        except ValueError:
            return -1

    @staticmethod
    def collect_expected_custom_ids(context_map: Dict[str, Any]) -> set:
        """
        Collect custom_ids of records that were submitted to batch API.

        Only counts records with _batch_filter_status='included' since filtered/skipped
        records were never submitted to the batch API.

        Args:
            context_map: Dictionary mapping custom_id to original record data

        Returns:
            Set of custom_ids that were actually submitted to batch API
        """
        return {
            str(custom_id)
            for custom_id, original_row in (context_map or {}).items()
            if original_row.get('_batch_filter_status', 'included') == 'included'
        }

    @staticmethod
    def collect_result_custom_ids(batch_results: List[Any]) -> set:
        """
        Collect custom_ids from batch results.

        Ignores internal error placeholders (error_line_*) which are not real missing
        records, just provider-side errors that need to be filtered out.

        Args:
            batch_results: List of BatchResult objects from provider

        Returns:
            Set of custom_ids that were returned in batch results
        """
        result_ids: set = set()
        for batch_result in batch_results or []:
            custom_id = getattr(batch_result, 'custom_id', None)
            if not custom_id:
                continue
            custom_id_str = str(custom_id)
            if custom_id_str.startswith('error_line_'):
                continue
            result_ids.add(custom_id_str)
        return result_ids

    @staticmethod
    def log_batch_reconciliation(
        *,
        batch_id: str,
        expected_count: int,
        received_count: int,
        file_name: Optional[str] = None
    ) -> None:
        """
        Log batch reconciliation status with visual indicators.

        Provides transparency into whether all expected results were received.
        Uses visual indicators (✅/⚠️) for quick scanning of batch health.

        Args:
            batch_id: Batch ID for context
            expected_count: Number of records submitted to batch API
            received_count: Number of results received from batch API
            file_name: Optional file name for better labeling (preferred over batch_id)
        """
        import logging
        logger = logging.getLogger(__name__)

        if expected_count == 0:
            return

        label = file_name or batch_id
        if expected_count == received_count:
            logger.info(
                'Batch reconciliation for %s: expected %d result(s), received %d',
                label, expected_count, received_count
            )
        else:
            logger.warning(
                'Batch reconciliation for %s: expected %d result(s), received %d',
                label, expected_count, received_count
            )
