"""FILE-granularity tool processing strategy."""

from __future__ import annotations

import copy
import logging
from typing import Any, cast

from agent_actions.errors import AgentActionsError
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.processing.record_helpers import build_tombstone
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

        Records are already cascade-filtered by UnifiedProcessor — only
        processable records arrive here.

        ``context.source_data`` must contain the pre-context-scope records
        that passed the guard and cascade filters (set by UnifiedProcessor
        before invoking the strategy).  These are used for output
        reconciliation.
        """
        original_data = context.source_data or []
        try:
            context_scope = context.agent_config.get("context_scope") or {}
            clean_input: list[TrackedItem] = []
            for i, record in enumerate(records):
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

            if is_empty_response(raw_response) and records:
                error_msg = (
                    f"Tool '{context.agent_name}' returned empty result "
                    f"from {len(records)} input record(s)"
                )
                return [
                    ProcessingResult.failed(
                        error=error_msg,
                        source_guid=record.get("source_guid"),
                        source_snapshot=copy.deepcopy(record),
                    )
                    for record in records
                ]

            structured_data, source_mapping = reconcile_outputs(
                raw_response,
                context.agent_name,
                original_data,
                version_merge=is_version_merge(context.agent_config),
            )

            is_expansion = len(structured_data) > len(records)

            # Detect missing records — tool dropped input without output.
            # Skip for expansion tools (N→M, M>N) where output GUIDs
            # legitimately differ from input GUIDs.
            # Also skip when synthetic records exist (source_mapping contains
            # None) — we can't determine which inputs a synthetic consumed.
            has_synthetic = source_mapping and any(v is None for v in source_mapping.values())
            missing_results: list[ProcessingResult] = []
            if not is_expansion and not has_synthetic:
                output_guids = {
                    item.get("source_guid") for item in structured_data if isinstance(item, dict)
                }
                for input_record in records:
                    rid = input_record.get("source_guid")
                    if rid and rid not in output_guids:
                        logger.warning(
                            "Tool '%s' did not return record %s — producing passthrough tombstone",
                            context.agent_name,
                            rid,
                        )
                        missing_results.append(
                            ProcessingResult.unprocessed(
                                data=[
                                    build_tombstone(
                                        context.agent_name,
                                        input_record,
                                        "tool_missing_record",
                                        source_guid=rid,
                                    )
                                ],
                                reason="tool_missing_record",
                                source_guid=rid,
                                input_record=input_record,
                            )
                        )

            result = ProcessingResult.success(
                data=structured_data,
                source_guid=None,  # FILE mode has no single source
                raw_response=raw_response,
                is_expansion=is_expansion,
            )
            result.executed = executed
            result.source_mapping = source_mapping

            return [result] + missing_results

        except AgentActionsError:
            raise
        except Exception as e:
            logger.error("FILE mode tool '%s' failed: %s", context.agent_name, e)
            raise AgentActionsError(
                f"FILE mode tool '{context.agent_name}' failed: {e}",
                context={
                    "agent_name": context.agent_name,
                    "record_count": len(records),
                    "operation": "file_mode_tool",
                },
                cause=e,
            ) from e
