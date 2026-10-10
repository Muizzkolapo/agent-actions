"""FILE-granularity tool processing strategy."""

from __future__ import annotations

import copy
import logging
from collections.abc import Sequence
from typing import Any, cast

from agent_actions.errors import (
    AgentActionsError,
    ConfigurationError,
    is_action_fatal,
    mark_action_fatal,
)
from agent_actions.errors.processing import EmptyOutputError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.diagnostics import DIAGNOSTIC
from agent_actions.logging.events.data_pipeline_events import RecordEmptyOutputEvent
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.processing.record_helpers import build_tombstone
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
)
from agent_actions.record.reasons import EMPTY_OUTPUT, TOOL_MISSING_RECORD
from agent_actions.record.tracking import TrackedItem, is_input_position
from agent_actions.utils.constants import MODEL_NAME_KEY
from agent_actions.utils.content import is_version_merge
from agent_actions.utils.tools_resolver import resolve_tools_path
from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.utils.udf_management.tooling import output_schema_errors
from agent_actions.workflow.pipeline_file_mode import (
    extract_tool_input,
    is_empty_response,
    reconcile_outputs,
)

logger = logging.getLogger(__name__)


def _collapse_contributor_guids(
    structured_data: list[dict[str, Any]],
    source_mapping: dict[int, int | list[int] | None] | None,
    records: list[dict[str, Any]],
    *,
    re_keyed: bool = False,
) -> list[str]:
    """Guids of inputs an output consumed but does not carry.

    An input missing from the result leaves no disposition row at the consuming action
    and is reprocessed on every retry. *re_keyed* when every row will be minted a fresh
    identity below this strategy, as lineage enrichment does for an expansion: no guid
    a row carries now survives, so none accounts for an input.
    """
    carried = set() if re_keyed else {item.get("source_guid") for item in structured_data}
    contributors: set[str] = set()
    for src in (source_mapping or {}).values():
        indices: Sequence[int | None] = src if isinstance(src, list) else (src,)
        for idx in indices:
            if is_input_position(idx, len(records)):
                guid = records[idx].get("source_guid")
                if guid and guid not in carried:
                    contributors.add(guid)
    return sorted(contributors)


def _unnamed_inputs(
    structured_data: list[dict[str, Any]],
    source_mapping: dict[int, int | list[int] | None] | None,
    records: list[dict[str, Any]],
) -> list[str]:
    """Inputs no output row names. A tool may expand while naming only some of them."""
    accounted = _accounted_source_guids(structured_data, source_mapping, records)
    return [
        guid for record in records if (guid := record.get("source_guid")) and guid not in accounted
    ]


def _accounted_source_guids(
    structured_data: list[dict[str, Any]],
    source_mapping: dict[int, int | list[int] | None] | None,
    records: list[dict[str, Any]],
) -> set[str | None]:
    """Source guids an output accounts for, including every contributor to a collapse.

    A many-to-one output inherits only its *first* parent's guid, so reading
    structured_data alone reports the other contributors as dropped. The mapping
    holds the full index list, which is the only place the rest survive.
    """
    accounted: set[str | None] = {item.get("source_guid") for item in structured_data}
    for src in (source_mapping or {}).values():
        indices: Sequence[int | None] = src if isinstance(src, list) else (src,)
        for idx in indices:
            if is_input_position(idx, len(records)):
                accounted.add(records[idx].get("source_guid"))
    return accounted


def _rows_named(raw_response: Any) -> list[list[int]]:
    """The input positions each row of the tool's output names, in output order."""
    if isinstance(raw_response, FileUDFResult):
        sources = [out["source_index"] for out in raw_response.outputs]
    elif isinstance(raw_response, list):
        sources = [
            item._source_index if isinstance(item, TrackedItem) else None for item in raw_response
        ]
    else:
        return []
    return [[] if src is None else src if isinstance(src, list) else [src] for src in sources]


def _withhold_refused_rows(
    raw_response: Any,
    output_schema: dict[str, Any],
    udf_name: str,
    record_count: int,
) -> tuple[Any, dict[int, str]]:
    """The tool's output less every row of each record the schema refused a row of, and
    the refusal of each such record, by its input position.

    Raises the first refusal when no one record answers for it: the refused row names
    several records or none, or a row withheld with a refused record names another.
    """
    errors = output_schema_errors(udf_name, raw_response, output_schema)
    if not errors:
        return raw_response, {}
    named = _rows_named(raw_response)
    refused: dict[int, str] = {}
    for idx, error in errors:
        sources = named[idx] if idx is not None else []
        if len(sources) != 1 or not is_input_position(sources[0], record_count):
            raise error
        refused.setdefault(sources[0], str(error))
    withheld = {i for i, sources in enumerate(named) if not refused.keys().isdisjoint(sources)}
    if any(set(named[i]) - refused.keys() for i in withheld):
        raise errors[0][1]
    if isinstance(raw_response, FileUDFResult):
        kept: Any = FileUDFResult(
            outputs=[out for i, out in enumerate(raw_response.outputs) if i not in withheld]
        )
    else:
        kept = [item for i, item in enumerate(raw_response) if i not in withheld]
    return kept, refused


def _failed(record: dict[str, Any], original: dict[str, Any], error: str) -> ProcessingResult:
    """Fail *record* as the record loop fails one whose tool raised.

    The tombstone is built from *original*, the record from before the scope.
    """
    return ProcessingResult.failed(
        error=error, source_guid=record.get("source_guid"), input_record=original
    )


def _originals(
    records: list[dict[str, Any]], original_data: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The record from before the scope for each of *records*, which pair to it by position."""
    return original_data if len(original_data) == len(records) else records


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
            clean_input: list[TrackedItem] = [
                TrackedItem(extract_tool_input(record, context_scope), source_index=i)
                for i, record in enumerate(records)
            ]

            agent_config = cast(dict[str, Any], context.agent_config)
            output_schema = agent_config.get("json_output_schema")
            raw_response, executed = run_dynamic_agent(
                # Checked below, row by row, where a refused row can fail its record alone.
                agent_config={**agent_config, "json_output_schema": None},
                agent_name=context.agent_name,
                context=clean_input,
                formatted_prompt="",
                tools_path=resolve_tools_path(agent_config),
            )

            if is_empty_response(raw_response) and records:
                on_empty = context.agent_config.get("on_empty", "warn")

                fire_event(
                    RecordEmptyOutputEvent(
                        action_name=context.agent_name,
                        record_index=-1,
                        source_guid="",
                        input_field_count=len(records),
                        output=raw_response,
                        on_empty=on_empty,
                    )
                )

                if on_empty == "error":
                    raise EmptyOutputError(
                        f"Tool '{context.agent_name}' returned empty result from "
                        f"{len(records)} input record(s) (on_empty=error)",
                        context={
                            "agent_name": context.agent_name,
                            "record_count": len(records),
                            "source_guids": [
                                r.get("source_guid") for r in records if r.get("source_guid")
                            ],
                        },
                    )

                if on_empty == "skip":
                    return [
                        ProcessingResult.skipped(
                            passthrough_data=build_tombstone(
                                context.agent_name,
                                record,
                                EMPTY_OUTPUT,
                                source_guid=record.get("source_guid"),
                            ),
                            reason=EMPTY_OUTPUT,
                            source_guid=record.get("source_guid"),
                            source_snapshot=copy.deepcopy(record),
                            input_record=record,
                        )
                        for record in records
                    ]

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

            refused: dict[int, str] = {}
            if output_schema:
                raw_response, refused = _withhold_refused_rows(
                    raw_response,
                    output_schema,
                    agent_config.get(MODEL_NAME_KEY) or context.agent_name,
                    len(records),
                )
            originals = _originals(records, original_data)
            refused_results = [
                _failed(records[at], originals[at], error) for at, error in sorted(refused.items())
            ]
            answered = [record for at, record in enumerate(records) if at not in refused]
            if refused and not answered:
                return refused_results

            structured_data, source_mapping = reconcile_outputs(
                raw_response,
                context.agent_name,
                original_data,
                version_merge=is_version_merge(context.agent_config),
                version_base_name=context.agent_config.get("version_base_name"),
            )

            is_expansion = len(structured_data) > len(answered)

            has_synthetic = source_mapping and any(v is None for v in source_mapping.values())
            missing_results: list[ProcessingResult] = []
            if not is_expansion and not has_synthetic:
                output_guids = _accounted_source_guids(structured_data, source_mapping, records)
                for input_record in answered:
                    rid = input_record.get("source_guid")
                    if rid and rid not in output_guids:
                        missing_results.append(
                            ProcessingResult.unprocessed(
                                data=[
                                    build_tombstone(
                                        context.agent_name,
                                        input_record,
                                        TOOL_MISSING_RECORD,
                                        source_guid=rid,
                                    )
                                ],
                                reason=TOOL_MISSING_RECORD,
                                source_guid=rid,
                                input_record=input_record,
                            )
                        )

                if missing_results:
                    n_missing = len(missing_results)
                    n_total = len(answered)
                    n_output = len(structured_data)
                    ratio = n_missing / n_total

                    if ratio > 0.5:
                        logger.warning(
                            "Tool '%s' did not return %d of %d input records "
                            "(produced %d outputs). "
                            "If this is a many-to-one tool (N inputs -> M outputs), "
                            "use a list for source_index to map all inputs:\n"
                            '  FileUDFResult(outputs=[{"source_index": [0, 1, 2, ...], "data": ...}])\n'
                            "Unmapped records will be passed through as tombstones.",
                            context.agent_name,
                            n_missing,
                            n_total,
                            n_output,
                        )
                    else:
                        missing_guids = [r.source_guid for r in missing_results if r.source_guid]
                        logger.warning(
                            "Tool '%s' did not return %d of %d records — "
                            "producing passthrough tombstones. "
                            "Missing source_guids: %s",
                            context.agent_name,
                            n_missing,
                            n_total,
                            missing_guids[:10],
                        )

            result = ProcessingResult.success(
                data=structured_data,
                source_guid=None,  # FILE mode has no single source
                raw_response=raw_response,
                is_expansion=is_expansion,
            )
            result.executed = executed
            result.source_mapping = source_mapping
            # Credited only where the next run could reproduce this result: every row
            # belongs to an input and every input is named. Otherwise the rewrite drops a
            # row nothing resolves, or the run is left holding only what was declined.
            failed_guids = {r.source_guid for r in refused_results}
            unnamed = set(_unnamed_inputs(structured_data, source_mapping, records)) - failed_guids
            if not has_synthetic and not unnamed:
                result.collapse_contributor_guids = _collapse_contributor_guids(
                    structured_data, source_mapping, records, re_keyed=is_expansion
                )

            # A refusal can withhold every row, which leaves no answer to collect.
            if refused and not structured_data:
                return missing_results + refused_results
            return [result] + missing_results + refused_results

        except (ConfigurationError, EmptyOutputError) as e:
            # A broken tool config and an on_empty: error mean the same thing
            # whether the granularity is a record or a file.
            mark_action_fatal(e)
            raise
        except Exception as e:
            if is_action_fatal(e):
                raise
            # The file's one result names no record, so each record handed to the tool
            # fails with it; raised, the walk lost the file with nothing naming them.
            logger.exception(
                "[%s] FILE mode tool failed on %d record(s): %s",
                context.agent_name,
                len(records),
                e,
                extra=DIAGNOSTIC,
            )
            error = (
                str(e)
                if isinstance(e, AgentActionsError)
                else f"FILE mode tool '{context.agent_name}' failed: {e}"
            )
            return [
                _failed(record, original, error)
                for record, original in zip(
                    records, _originals(records, original_data), strict=True
                )
            ]
