"""Shared result aggregation for processing output records."""

import logging
from typing import Any, Dict, List

from agent_actions.processing.exhausted_builder import ExhaustedRecordBuilder
from agent_actions.processing.types import ProcessingResult, ProcessingStatus
from agent_actions.errors import AgentActionsException

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
    ) -> List[Dict[str, Any]]:
        """
        Flatten ProcessingResult entries into output records.

        Args:
            results: Processing results to aggregate.
            agent_config: Agent configuration for schema hints.
            agent_name: Agent name for exhausted record lineage.
            is_first_stage: True for staging, False for downstream.
        Returns:
            List of output records.
        Raises:
            AgentActionsException: If on_exhausted=raise and records exhausted retries.
        """
        # Check on_exhausted config for raise behavior
        exhausted_results = [r for r in results if r.status == ProcessingStatus.EXHAUSTED]

        if exhausted_results:
            retry_config = agent_config.get("retry", {})
            on_exhausted = retry_config.get("on_exhausted", "return_last")

            logger.warning(
                "[%s] %d records have exhausted retries (on_exhausted=%s)",
                agent_name,
                len(exhausted_results),
                on_exhausted,
            )

            if on_exhausted == "raise":
                exhausted_record = exhausted_results[0]
                attempts = (
                    exhausted_record.recovery_metadata.retry.attempts
                    if exhausted_record.recovery_metadata
                    and exhausted_record.recovery_metadata.retry
                    else "unknown"
                )
                raise AgentActionsException(
                    f"Retry exhausted for record {exhausted_record.source_guid} after "
                    f"{attempts} attempts (on_exhausted=raise)",
                    context={
                        "agent_name": agent_name,
                        "exhausted_records": len(exhausted_results),
                        "on_exhausted": "raise",
                    },
                )

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
                if data:
                    output.extend(data)
                logger.debug(
                    "Collected SKIPPED result source_guid=%s count=%d",
                    result.source_guid,
                    len(data),
                )
            elif result.status == ProcessingStatus.EXHAUSTED:
                if result.recovery_metadata and result.recovery_metadata.retry:
                    # First stage uses source_snapshot, downstream uses input_record
                    if is_first_stage:
                        original_row = result.source_snapshot
                    else:
                        original_row = result.input_record
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
