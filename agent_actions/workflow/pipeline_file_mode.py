"""FILE-granularity processing helpers.

Shared utilities for FILE-mode strategies: source mapping, input extraction,
record building, output reconciliation, guard pre-filtering.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from agent_actions.record.tracking import TrackedItem

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


def _extract_tool_input(record: dict, context_scope: Mapping[str, Any]) -> dict:
    """Extract observed business fields from an enriched record for tool input.

    Reads from enriched content where drops have already been applied by
    ``apply_context_scope_for_records()``.  Uses ``parse_field_reference()``
    for validated ref parsing instead of the former ``str.split()`` shadow.

    When no observe is configured, flattens all content namespaces.
    """
    from agent_actions.prompt.context.scope_parsing import parse_field_reference

    content = record.get("content")
    if not isinstance(content, dict):
        return {}

    observe_refs = context_scope.get("observe", [])

    if not observe_refs:
        # No observe declared — flatten all content namespaces
        business: dict = {}
        for ns_data in content.values():
            if isinstance(ns_data, dict):
                business.update(ns_data)
        return business

    # Extract observed fields from post-drop enriched content.
    # Drops were already applied by apply_context_scope_for_records().
    business = {}
    for ref in observe_refs:
        try:
            ns, field = parse_field_reference(ref)
        except ValueError:
            continue  # Bad ref — already logged by scope application
        ns_data = content.get(ns)
        if not isinstance(ns_data, dict):
            continue
        if field == "*":
            business.update(ns_data)
        elif field in ns_data:
            business[field] = ns_data[field]

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
) -> tuple[list[dict[str, Any]], dict[int, int | list[int] | None]]:
    """Core reconciliation of tool output to input records.

    Dispatches on response type (``FileUDFResult`` vs ``TrackedItem`` list),
    builds records, and reattaches ``source_guid``.

    Returns ``(structured_data, source_mapping)``.
    """
    from agent_actions.utils.udf_management.registry import FileUDFResult

    source_mapping: dict[int, int | list[int] | None] = {}
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
    context_scope: dict[str, Any] = {"observe": observe_refs} if observe_refs else {}
    return [
        TrackedItem(_extract_tool_input(record, context_scope), source_index=i)
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
    from agent_actions.utils.content import get_existing_content

    evaluator = get_guard_evaluator()
    # The config expander normalizes user-facing "on_false" into "behavior"
    behavior = GuardBehavior(guard_config.get("behavior", "filter"))

    passing: list[dict] = []
    skipped: list[dict] = []
    original_passing: list[dict] = []
    for idx, item in enumerate(data):
        eval_item = get_existing_content(item)

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
