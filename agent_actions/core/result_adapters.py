"""Adapters for converting ProcessingResult to legacy return types.

This module provides backward-compatible adapters for converting the new
ProcessingResult objects to legacy formats expected by existing code.

Usage:
    from agent_actions.core.result_adapters import ProcessingResultAdapter

    # For first-stage processing
    data_chunk, src_text = ProcessingResultAdapter.to_staging_tuple(results)

    # For subsequent-stage processing
    output = ProcessingResultAdapter.to_list(results)
"""

from typing import Any, Dict, List, Tuple

from .types import ProcessingResult, ProcessingStatus


class ProcessingResultAdapter:
    """Converts ProcessingResult to legacy formats for backward compatibility."""

    @staticmethod
    def to_staging_tuple(
        results: List[ProcessingResult],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Convert ProcessingResults to (data_chunk, src_text) tuple.

        Used for first-stage processing to maintain compatibility with the
        legacy StagingProcessor return format.

        Args:
            results: List of ProcessingResult from RecordProcessor

        Returns:
            Tuple of (data_chunk, src_text):
            - data_chunk: List of processed output dicts
            - src_text: List of source items with source_guid for saving
        """
        data_chunk: List[Dict[str, Any]] = []
        src_text: List[Dict[str, Any]] = []

        for result in results:
            # Add source snapshot to src_text for ALL results (even filtered)
            # This ensures source data is saved for downstream agents
            if result.source_snapshot is not None:
                src_item = result.source_snapshot
                if isinstance(src_item, dict):
                    src_item = src_item.copy()
                    src_item["source_guid"] = result.source_guid
                else:
                    src_item = {"content": src_item, "source_guid": result.source_guid}
                src_text.append(src_item)

            # Skip filtered items from data_chunk (they shouldn't be processed)
            if result.status == ProcessingStatus.FILTERED:
                continue

            # Add processed data to data_chunk
            data_chunk.extend(result.data)

        return data_chunk, src_text

    @staticmethod
    def to_list(results: List[ProcessingResult]) -> List[Dict[str, Any]]:
        """
        Convert ProcessingResults to flat list of dicts.

        Used for subsequent-stage processing to maintain compatibility with
        the legacy return format.

        Args:
            results: List of ProcessingResult from RecordProcessor

        Returns:
            List of processed data dicts (filtered items excluded)
        """
        output: List[Dict[str, Any]] = []
        for result in results:
            # Skip filtered items
            if result.status == ProcessingStatus.FILTERED:
                continue
            output.extend(result.data)
        return output
