"""FILE-granularity processing handlers extracted from ProcessingPipeline.

These standalone functions handle tool and HITL processing when granularity
is ``file`` — i.e. the entire input array is passed as one unit rather than
looping per-record.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agent_actions.errors import AgentActionsError
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.record.tracking import TrackedItem

if TYPE_CHECKING:
    from agent_actions.workflow.pipeline import ProcessingPipeline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_source_mapping(
    raw_outputs: list[dict],
    input_data: list[dict],
    action_name: str,
) -> dict[int, int | list[int]]:
    """Resolve which input produced each output by ``node_id``.

    NiFi-inspired: every record carries identity (``node_id``) through the
    pipeline.  The framework preserves it through the observe filter; tools
    receive full records and pass them through.  The framework matches each
    output to its input by ``node_id`` — no heuristics, no guessing.

    Returns a mapping of ``output_index -> input_index`` for outputs that
    carry a ``node_id`` matching an input.  Outputs without a matching
    ``node_id`` are omitted — they are new records (e.g. aggregation
    results) and will receive fresh lineage with no parent.
    """
    # Build lookup: node_id -> input index
    nid_to_idx: dict[str, int] = {}
    for i, item in enumerate(input_data):
        if isinstance(item, dict):
            nid = item.get("node_id")
            if isinstance(nid, str):
                nid_to_idx[nid] = i

    mapping: dict[int, int | list[int]] = {}
    for i, item in enumerate(raw_outputs):
        nid = item.get("node_id") if isinstance(item, dict) else None
        if not isinstance(nid, str):
            logger.warning(
                "FILE tool '%s': output[%d] has no node_id. "
                "Record will get fresh lineage with no parent.",
                action_name,
                i,
            )
            continue
        if nid not in nid_to_idx:
            logger.warning(
                "FILE tool '%s': output[%d] has node_id '%s' not found in inputs. "
                "Treating as new record.",
                action_name,
                i,
                nid,
            )
            continue
        mapping[i] = nid_to_idx[nid]

    return mapping


def _reattach_source_guid(
    structured_data: list[dict],
    source_mapping: dict[int, int | list[int] | None] | None,
    original_data: list[dict],
) -> None:
    """Reattach source_guid from input records to output items using mapping.

    Mutates structured_data in place.  Only sets source_guid when the output
    item does not already carry a truthy value (explicit tool values win).
    Entries with ``None`` source index (synthetic records) are skipped.
    """
    if source_mapping is None or not original_data:
        return

    for i, item in enumerate(structured_data):
        if item.get("source_guid"):
            continue  # Tool explicitly set it — respect that

        if i not in source_mapping:
            # Positional fallback only when ALL outputs lack node_id (empty mapping)
            # and cardinalities match (1:1 passthrough by tools that don't preserve node_id).
            # When mapping has entries, unmapped outputs are genuinely new records.
            if not source_mapping and len(structured_data) == len(original_data):
                source_idx: int | list[int] | None = i
            else:
                continue  # Unmapped output — new record, no parent to inherit from
        else:
            source_idx = source_mapping[i]

        if source_idx is None:
            continue  # Synthetic record — no parent GUID to inherit

        if isinstance(source_idx, list):
            source_idx = source_idx[0]  # Many-to-one: use first parent

        if isinstance(source_idx, int) and source_idx < len(original_data):
            parent_guid = original_data[source_idx].get("source_guid")
            if parent_guid:
                item["source_guid"] = parent_guid


def _resolve_input_record(
    input_idx: int | None, original_data: list[dict]
) -> dict[str, Any] | None:
    """Resolve the input record for namespace carry-forward.

    When *input_idx* is ``None`` (synthetic record), falls back to
    ``original_data[0]`` — all records in a batch share upstream namespaces.
    Raises ``IndexError`` for out-of-bounds non-None indices.
    """
    if not original_data:
        return None
    if input_idx is None:
        return original_data[0]
    if not isinstance(input_idx, int) or input_idx < 0 or input_idx >= len(original_data):
        raise IndexError(
            f"source_index {input_idx} is out of bounds for {len(original_data)} input records"
        )
    return original_data[input_idx]


def _extract_business_fields(record: dict, agent_config: Mapping[str, Any]) -> dict:
    """Extract observe-filtered business fields from a record for tool input.

    Strips all framework fields.  Returns only business data from observed
    namespaces.  When no observe is configured, flattens all content namespaces.
    """
    content = record.get("content")
    if not isinstance(content, dict):
        return {}

    context_scope = agent_config.get("context_scope") or {}
    observe_refs = context_scope.get("observe", [])

    if not observe_refs:
        # No observe declared — flatten all content namespaces
        business: dict = {}
        for ns_data in content.values():
            if isinstance(ns_data, dict):
                business.update(ns_data)
        return business

    # Extract only observed fields
    business = {}
    for ref in observe_refs:
        if "." not in ref:
            continue
        ns, field = ref.split(".", 1)
        if ns not in content or not isinstance(content[ns], dict):
            continue
        if field == "*":
            business.update(content[ns])
        elif field in content[ns]:
            business[field] = content[ns][field]

    return business


def _build_record(
    action_name: str,
    data_fields: dict,
    matched: dict[str, Any] | None,
    version_merge: bool,
) -> dict[str, Any]:
    """Build a single output record, either namespaced or version-merge spread."""
    if version_merge:
        from agent_actions.utils.content import get_existing_content

        existing = get_existing_content(matched) if matched else {}
        record: dict[str, Any] = {"content": {**existing, **data_fields}}
    else:
        from agent_actions.record.envelope import RecordEnvelope

        record = RecordEnvelope.build(action_name, data_fields, matched)
    record.pop("source_guid", None)
    return record


def _reconcile_outputs(
    raw_response: Any,
    action_name: str,
    original_data: list[dict],
    version_merge: bool = False,
) -> tuple[list[dict[str, Any]], dict[int, int | list[int]]]:
    """Core reconciliation of tool output to input records.

    Dispatches on response type (``FileUDFResult`` vs ``TrackedItem`` list),
    builds records, and reattaches ``source_guid``.

    Returns ``(structured_data, source_mapping)``.
    """
    from agent_actions.utils.udf_management.registry import FileUDFResult

    source_mapping: dict[int, int | list[int]] = {}
    structured_data: list[dict[str, Any]] = []

    if isinstance(raw_response, FileUDFResult):
        for i, out in enumerate(raw_response.outputs):
            src_idx = out["source_index"]
            if src_idx is None:
                input_idx = None
            elif isinstance(src_idx, list):
                input_idx = src_idx[0]
            else:
                input_idx = src_idx
            source_mapping[i] = src_idx

            matched = _resolve_input_record(input_idx, original_data)
            structured_data.append(_build_record(action_name, out["data"], matched, version_merge))

    elif isinstance(raw_response, list):
        for i, item in enumerate(raw_response):
            if isinstance(item, TrackedItem):
                source_mapping[i] = item._source_index
                matched = _resolve_input_record(item._source_index, original_data)
                structured_data.append(
                    _build_record(action_name, dict(item), matched, version_merge)
                )
            elif isinstance(item, dict):
                raise ValueError(
                    f"FILE tool '{action_name}' returned plain dict at "
                    f"output[{i}]. Tool created a new dict instead of returning "
                    f"an input item. For merge/expand, use FileUDFResult with "
                    f"source_index."
                )
            else:
                raise ValueError(
                    f"FILE tool '{action_name}' output[{i}] is "
                    f"{type(item).__name__}, expected TrackedItem. "
                    f"For N→M transforms, use FileUDFResult."
                )
    else:
        raise ValueError(
            f"FILE tool '{action_name}' must return list or FileUDFResult, "
            f"got {type(raw_response).__name__}"
        )

    _reattach_source_guid(structured_data, source_mapping, original_data)
    return structured_data, source_mapping


# ---------------------------------------------------------------------------
# Public API — standalone helpers for testing / simulation
# ---------------------------------------------------------------------------


def framework_prepare_input(
    records: list[dict],
    observe_refs: list[str] | None = None,
) -> list[TrackedItem]:
    """Strip framework fields and wrap in TrackedItem for tool input."""
    config: dict[str, Any] = {"context_scope": {"observe": observe_refs}} if observe_refs else {}
    return [
        TrackedItem(_extract_business_fields(record, config), source_index=i)
        for i, record in enumerate(records)
    ]


def framework_reconcile(
    raw_response: Any,
    action_name: str,
    original_data: list[dict],
) -> list[dict[str, Any]]:
    """Reconcile tool output to input records via provenance.

    Standalone wrapper over ``_reconcile_outputs`` for design tests and
    simulations.
    """
    data, _ = _reconcile_outputs(raw_response, action_name, original_data)
    return data


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


def _is_empty_response(raw_response: Any) -> bool:
    """Check if tool returned an empty response."""
    from agent_actions.utils.udf_management.registry import FileUDFResult

    if isinstance(raw_response, FileUDFResult):
        return not raw_response.outputs
    if isinstance(raw_response, list):
        return not raw_response
    return False


def process_file_mode_tool(
    pipeline: ProcessingPipeline,
    data: list[dict],
    original_data: list[dict],
    context: ProcessingContext,
) -> list:
    """Process tool in FILE granularity mode.

    Tools receive clean business data wrapped in ``TrackedItem`` — no
    framework fields leak into user code.  After the tool returns, the
    framework reconciles output to input via ``TrackedItem._source_index``
    (for N→N list returns) or ``FileUDFResult.source_index`` (for N→M
    transforms).  Plain dicts in list returns are an error.
    """
    try:
        clean_input: list[TrackedItem] = []
        for i, record in enumerate(data):
            business = _extract_business_fields(record, context.agent_config)
            clean_input.append(TrackedItem(business, source_index=i))

        raw_response, executed = run_dynamic_agent(
            agent_config=cast(dict[str, Any], context.agent_config),
            agent_name=context.agent_name,
            context=clean_input,
            formatted_prompt="",
            tools_path=context.agent_config.get("tools_path"),
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

        # Run enrichment on ALL items in result
        result = pipeline.record_processor.enrichment_pipeline.enrich(result, context)

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


def process_file_mode_hitl(
    pipeline: ProcessingPipeline,
    data: list[dict],
    original_data: list[dict],
    context: ProcessingContext,
) -> list:
    """Process HITL action in FILE granularity mode.

    Invokes HITL once with the full array and applies the single file-level
    decision payload to every record so downstream stages retain full dataset
    cardinality.

    Args:
        pipeline: The parent ``ProcessingPipeline`` instance.
        data: Observe-filtered records (shown to HITL UI).
        original_data: Unfiltered records (used for merge to preserve all fields).
        context: Processing context.
    """
    try:
        # Inject HITL state persistence metadata into agent config
        hitl_agent_config = dict(context.agent_config)
        if context.output_directory:
            hitl_state_dir = str(Path(context.output_directory) / "hitl")
            # Derive a collision-proof, filesystem-safe key from the full
            # input path AND agent name.  Including the agent name ensures
            # multiple FILE-mode HITL actions on the same file get distinct
            # state files.  The hex hash avoids separator collisions and
            # platform-invalid characters (e.g. Windows drive-letter colons).
            identity = f"{context.file_path or 'default'}:{context.agent_name}"
            file_stem = sha256(identity.encode()).hexdigest()[:16]
            hitl_agent_config["_hitl_state_dir"] = hitl_state_dir
            hitl_agent_config["_hitl_file_stem"] = file_stem

        raw_response, executed = run_dynamic_agent(
            agent_config=hitl_agent_config,
            agent_name=context.agent_name,
            context=data,
            formatted_prompt="",
            tools_path=cast(str | None, hitl_agent_config.get("tools_path")),
        )

        # Unwrap single-item list from invocation service
        if isinstance(raw_response, list) and len(raw_response) == 1:
            decision_payload = raw_response[0]
        elif isinstance(raw_response, list):
            raise ValueError(
                "FILE mode HITL must return a single decision payload, "
                f"got {len(raw_response)} items"
            )
        else:
            decision_payload = raw_response

        if not isinstance(decision_payload, dict):
            raise ValueError(
                "FILE mode HITL must return an object payload, "
                f"got {type(decision_payload).__name__}"
            )

        # Detect timeout — partial reviews are persisted on disk; raise so
        # the agent is marked failed and re-runs will resume from state.
        if decision_payload.get("hitl_status") == "timeout":
            reviewed = sum(
                1 for r in (decision_payload.get("record_reviews") or []) if r is not None
            )
            raise AgentActionsError(
                f"HITL review timed out ({reviewed}/{len(data)} records reviewed). "
                "Partial reviews saved. Re-run workflow to resume.",
                context={
                    "agent_name": context.agent_name,
                    "record_count": len(data),
                },
            )

        record_reviews = (
            decision_payload.get("record_reviews")
            if isinstance(decision_payload.get("record_reviews"), list)
            else None
        )
        # Only propagate HITL decision metadata. Keep source business fields
        # (for example `status`) intact.
        decision_common = {
            key: value
            for key, value in decision_payload.items()
            if key in {"hitl_status", "user_comment", "timestamp"}
        }

        # Propagate one file-level decision across all input records so
        # downstream processing keeps record cardinality intact.
        # Use original_data for the merge to preserve all upstream fields.
        from agent_actions.record.envelope import RecordEnvelope

        structured_data = []
        if original_data:
            for idx, item in enumerate(original_data):
                hitl_output = dict(decision_common)
                if record_reviews and idx < len(record_reviews):
                    review_payload = record_reviews[idx]
                    if isinstance(review_payload, dict):
                        for key in ("hitl_status", "user_comment"):
                            if key in review_payload:
                                hitl_output[key] = review_payload[key]

                record = RecordEnvelope.build(context.agent_name, hitl_output, item)

                # Carry framework fields that RecordEnvelope doesn't manage.
                for field in ("target_id", "_unprocessed", "_recovery", "metadata"):
                    if field in item:
                        record[field] = item[field]
                structured_data.append(record)

        # HITL FILE mode is always 1:1 — identity source_mapping ensures the
        # enricher extends parent lineage rather than truncating to [node_id].
        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=structured_data,
            source_guid=None,
            raw_response=raw_response,
            executed=executed,
            source_mapping={i: i for i in range(len(structured_data))},
        )

        result = pipeline.record_processor.enrichment_pipeline.enrich(result, context)
        return [result]
    except AgentActionsError:
        raise
    except Exception:
        logger.exception("Unexpected error in FILE mode HITL processing")
        raise


def prefilter_by_guard(
    data: list[dict],
    agent_config: dict[str, Any],
    agent_name: str,
    original_data: list[dict] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Evaluate guard per-record and split into passing and skipped arrays.

    Called before FILE-mode processing to apply per-record guard logic
    on the full array.  ``behavior: filter`` records are excluded from
    both returned lists.  ``behavior: skip`` records land in *skipped*
    so the caller can merge them back into output with original content.

    When ``original_data`` is provided (e.g. pre-observe-filter records),
    the third return value contains the corresponding original items for
    each passing record.  This preserves upstream fields that observe
    filtering may have stripped.

    When no guard is configured, returns ``(data, [], original_data or data)``.

    Note:
        Guard evaluation uses ``context={}`` because the pre-filter runs
        before processing context (passthrough fields, source data) is
        established.  Guard clauses in FILE-mode pre-filter can only
        reference item-level fields, not workflow context variables.

    Returns:
        (passing, skipped, original_passing)
    """
    originals = original_data if original_data is not None else data

    guard_config = agent_config.get("guard")
    if not guard_config:
        return data, [], originals

    from agent_actions.input.preprocessing.filtering.evaluator import (
        GuardBehavior,
        get_guard_evaluator,
    )

    evaluator = get_guard_evaluator()
    # The config expander normalizes user-facing "on_false" into "behavior"
    behavior = GuardBehavior(guard_config.get("behavior", "filter"))

    passing: list[dict] = []
    skipped: list[dict] = []
    original_passing: list[dict] = []
    for idx, item in enumerate(data):
        content = item.get("content", item)
        eval_item = content if isinstance(content, dict) else {"_raw": content}

        # context={} — see Note in docstring.
        result = evaluator.evaluate(
            item=eval_item,
            guard_config=guard_config,
            context={},
        )

        if result.should_execute:
            passing.append(item)
            original_passing.append(originals[idx])
        elif behavior == GuardBehavior.SKIP:
            # Use pre-observe original so skipped tombstones keep namespaced content.
            skipped.append(originals[idx])
        # behavior == GuardBehavior.FILTER: record excluded from both lists

    logger.info(
        "Guard pre-filter for '%s': %d passed, %d skipped, %d filtered of %d total",
        agent_name,
        len(passing),
        len(skipped),
        len(data) - len(passing) - len(skipped),
        len(data),
    )

    return passing, skipped, original_passing
