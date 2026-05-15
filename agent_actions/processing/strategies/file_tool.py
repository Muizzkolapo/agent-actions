"""FILE-granularity tool processing strategy."""

from __future__ import annotations

import copy
import logging
from typing import Any, cast

from agent_actions.errors import AgentActionsError
from agent_actions.processing.cascade_filter import partition_cascade_records
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
)
from agent_actions.record.tracking import TrackedItem
from agent_actions.utils.content import is_version_merge
from agent_actions.utils.tools_resolver import resolve_tools_path
from agent_actions.workflow.pipeline_file_mode import (
    extract_tool_input,
    is_empty_response,
    reconcile_outputs,
)

logger = logging.getLogger(__name__)


class FileToolStrategy:
    """Strategy for FILE-granularity tool invocation.

    Tools receive clean business data wrapped in ``TrackedItem`` — no
    framework fields leak into user code.  After the tool returns, the
    framework reconciles output to input via ``TrackedItem._source_index``
    (for N->N list returns) or ``FileUDFResult.source_index`` (for N->M
    transforms).  Plain dicts in list returns are an error.

    Conforms to the ``ProcessingStrategy`` protocol so it can be used
    with ``UnifiedProcessor.process()``.  Enrichment is handled by the
    processor, not by this strategy.
    """

    def invoke(
        self,
        records: list[dict[str, Any]],
        context: ProcessingContext,
    ) -> list[ProcessingResult]:
        """Invoke a FILE-mode tool and reconcile outputs.

        Cascade-blocking records (FAILED/EXHAUSTED/CASCADE_SKIPPED from
        upstream) are partitioned out before the tool runs — no tool
        invocation for quarantined records.

        ``context.source_data`` must contain the pre-context-scope records
        that passed the guard filter (set by UnifiedProcessor before
        invoking the strategy).  These are used for output reconciliation.
        """
        processable, quarantined_results = partition_cascade_records(
            records, action_name=context.agent_name
        )

        if not processable and quarantined_results:
            return list(quarantined_results)

        original_data = context.source_data
        try:
            context_scope = context.agent_config.get("context_scope") or {}
            clean_input: list[TrackedItem] = []
            for i, record in enumerate(processable):
                business = extract_tool_input(record, context_scope)
                clean_input.append(TrackedItem(business, source_index=i))

            agent_config = cast(dict[str, Any], context.agent_config)
            raw_response, executed = run_dynamic_agent(
                agent_config=agent_config,
                agent_name=context.agent_name,
                context=clean_input,
                formatted_prompt="",
                tools_path=resolve_tools_path(agent_config),
                skip_guard_eval=True,
            )

            if is_empty_response(raw_response) and processable:
                # FILE mode collapses all input records into one failure result.
                # Snapshot captures only processable[0] — for multi-record batches the
                # error message includes the total count for context.
                return quarantined_results + [
                    ProcessingResult.failed(
                        error=(
                            f"Tool '{context.agent_name}' returned empty result "
                            f"from {len(processable)} input record(s)"
                        ),
                        source_snapshot=copy.deepcopy(processable[0]) if processable else None,
                    )
                ]

            structured_data, source_mapping = reconcile_outputs(
                raw_response,
                context.agent_name,
                original_data,
                version_merge=is_version_merge(context.agent_config),
            )

            result = ProcessingResult.success(
                data=structured_data,
                source_guid=None,  # FILE mode has no single source
                raw_response=raw_response,
                is_expansion=len(structured_data) > len(processable),
            )
            result.executed = executed
            result.source_mapping = source_mapping

            return quarantined_results + [result]

        except AgentActionsError:
            raise
        except Exception as e:
            logger.error("FILE mode tool '%s' failed: %s", context.agent_name, e)
            raise AgentActionsError(
                f"FILE mode tool '{context.agent_name}' failed: {e}",
                context={
                    "agent_name": context.agent_name,
                    "record_count": len(processable),
                    "operation": "file_mode_tool",
                },
                cause=e,
            ) from e
