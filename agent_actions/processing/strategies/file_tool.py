"""FILE-granularity tool processing strategy."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from agent_actions.errors import AgentActionsError
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.record.tracking import TrackedItem
from agent_actions.workflow.pipeline_file_mode import (
    _extract_tool_input,
    _is_empty_response,
    _reconcile_outputs,
)

if TYPE_CHECKING:
    from agent_actions.processing.enrichment import EnrichmentPipeline

logger = logging.getLogger(__name__)


class FileToolStrategy:
    """Strategy for FILE-granularity tool invocation.

    Tools receive clean business data wrapped in ``TrackedItem`` — no
    framework fields leak into user code.  After the tool returns, the
    framework reconciles output to input via ``TrackedItem._source_index``
    (for N->N list returns) or ``FileUDFResult.source_index`` (for N->M
    transforms).  Plain dicts in list returns are an error.
    """

    def __init__(self, enrichment_pipeline: EnrichmentPipeline) -> None:
        self.enrichment_pipeline = enrichment_pipeline

    def invoke(
        self,
        data: list[dict],
        original_data: list[dict],
        context: ProcessingContext,
    ) -> list[ProcessingResult]:
        """Invoke a FILE-mode tool and reconcile outputs."""
        try:
            context_scope = context.agent_config.get("context_scope") or {}
            clean_input: list[TrackedItem] = []
            for i, record in enumerate(data):
                business = _extract_tool_input(record, context_scope)
                clean_input.append(TrackedItem(business, source_index=i))

            raw_response, executed = run_dynamic_agent(
                agent_config=cast(dict[str, Any], context.agent_config),
                agent_name=context.agent_name,
                context=clean_input,
                formatted_prompt="",
                tools_path=context.agent_config.get("tools_path"),
                skip_guard_eval=True,
            )

            if _is_empty_response(raw_response) and data:
                return [
                    ProcessingResult.failed(
                        error=(
                            f"Tool '{context.agent_name}' returned empty result "
                            f"from {len(data)} input record(s)"
                        ),
                    )
                ]

            from agent_actions.utils.content import is_version_merge

            structured_data, source_mapping = _reconcile_outputs(
                raw_response,
                context.agent_name,
                original_data,
                version_merge=is_version_merge(context.agent_config),
            )

            result = ProcessingResult(
                status=ProcessingStatus.SUCCESS,
                data=structured_data,
                source_guid=None,  # FILE mode has no single source
                raw_response=raw_response,
                executed=executed,
                source_mapping=source_mapping,
            )

            result = self.enrichment_pipeline.enrich(result, context)

            return [result]

        except Exception as e:
            logger.error("FILE mode tool '%s' failed: %s", context.agent_name, e)
            raise AgentActionsError(
                f"FILE mode tool '{context.agent_name}' failed: {e}",
                context={
                    "agent_name": context.agent_name,
                    "record_count": len(data),
                    "operation": "file_mode_tool",
                },
                cause=e,
            ) from e
