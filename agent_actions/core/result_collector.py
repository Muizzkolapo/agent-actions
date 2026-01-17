"""Shared result aggregation for processing output records."""

import logging
from typing import Any, Dict, List

from agent_actions.core.exhausted_record_builder import ExhaustedRecordBuilder
from agent_actions.core.types import ProcessingResult, ProcessingStatus

logger = logging.getLogger(__name__)


class ResultCollector:
    """Collect output records from processing results."""

    @staticmethod
    def collect_results(
        results: List[ProcessingResult],
        agent_config: Dict[str, Any],
        agent_name: str,
        *,
        is_first_stage: bool,
        include_skipped: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Flatten ProcessingResult entries into output records.

        Args:
            results: Processing results to aggregate.
            agent_config: Agent configuration for schema hints.
            agent_name: Agent name for exhausted record lineage.
            is_first_stage: True for staging, False for downstream.
            include_skipped: Whether to include skipped records.

        Returns:
            List of output records.
        """
        output: List[Dict[str, Any]] = []

        for result in results:
            if result.status == ProcessingStatus.SUCCESS:
                data = result.data or []
                if data:
                    output.extend(data)
                logger.debug(
                    "Collected SUCCESS result source_guid=%s count=%d",
                    result.source_guid,
                    len(data),
                )
            elif result.status == ProcessingStatus.SKIPPED:
                data = result.data or []
                if include_skipped and data:
                    output.extend(data)
                logger.debug(
                    "Collected SKIPPED result source_guid=%s count=%d include=%s",
                    result.source_guid,
                    len(data),
                    include_skipped,
                )
            elif result.status == ProcessingStatus.EXHAUSTED:
                if result.recovery_metadata and result.recovery_metadata.retry:
                    if is_first_stage and result.input_record is not None:
                        original_row = result.input_record
                    else:
                        original_row = result.source_snapshot
                    exhausted_item = ExhaustedRecordBuilder.build_exhausted_item(
                        source_guid=result.source_guid,
                        original_row=original_row,
                        recovery_metadata=result.recovery_metadata,
                        agent_config=agent_config,
                        action_name=agent_config.get("agent_type", agent_name),
                    )
                    output.append(exhausted_item)
                    logger.debug(
                        "Collected EXHAUSTED result source_guid=%s attempts=%s",
                        result.source_guid,
                        result.recovery_metadata.retry.attempts,
                    )
                else:
                    logger.debug(
                        "Skipped EXHAUSTED result without retry metadata source_guid=%s",
                        result.source_guid,
                    )
            elif result.status == ProcessingStatus.FAILED:
                logger.error("Processing failed: %s", result.error)
            elif result.status == ProcessingStatus.FILTERED:
                logger.debug("Collected FILTERED result source_guid=%s", result.source_guid)
            else:
                logger.debug("Unhandled result status=%s", result.status)

        return output
