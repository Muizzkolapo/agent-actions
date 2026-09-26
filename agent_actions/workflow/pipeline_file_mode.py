"""FILE-granularity processing helpers.

Shared utilities for FILE-mode strategies: source mapping, input extraction,
record building, output reconciliation, guard pre-filtering.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, cast

from agent_actions.record.tracking import TrackedItem, is_input_position

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parent_index(
    output_index: int,
    structured_data: list[dict],
    source_mapping: dict[int, int | list[int] | None] | None,
    original_data: list[dict],
) -> int | None:
    """The input row an output inherits from, or None if it has no single parent."""
    source_idx: int | list[int] | None = None
    if source_mapping is not None:
        if output_index in source_mapping:
            source_idx = source_mapping[output_index]
        elif not source_mapping and len(structured_data) == len(original_data):
            # Empty mapping + matching cardinality: 1:1 passthrough by a tool
            # that didn't preserve node_id.
            source_idx = output_index

    if isinstance(source_idx, list):
        source_idx = source_idx[0] if source_idx else None  # Many-to-one: first parent

    if original_data and is_input_position(source_idx, len(original_data)):
        return source_idx
    return None


def _consumed_guids(
    output_index: int,
    structured_data: list[dict],
    source_mapping: dict[int, int | list[int] | None] | None,
    original_data: list[dict],
) -> list[str]:
    """Identities of every input an output consumed, in mapping order.

    Read off the mapping rather than off the guid the row is replacing: that guid may
    itself have been minted by this action a step earlier, and would name no input.
    """
    if source_mapping is not None and source_mapping.get(output_index, False) is None:
        # Mapped to no input: the row is the tool's own invention. Resolving it to one
        # anyway — as the neighbouring _resolve_input_record does for namespaces — would
        # hand that input's carry a row it never produced.
        return []

    source_idx: int | list[int] | None = None
    if source_mapping is not None:
        if output_index in source_mapping:
            source_idx = source_mapping[output_index]
        elif not source_mapping and len(structured_data) == len(original_data):
            source_idx = output_index

    indices: Sequence[int | None] = source_idx if isinstance(source_idx, list) else (source_idx,)
    guids: list[str] = []
    for idx in indices:
        if isinstance(idx, int) and 0 <= idx < len(original_data):
            guid = original_data[idx].get("source_guid")
            if guid and guid not in guids:
                guids.append(guid)
    return guids


def _reattach_source_guid(
    structured_data: list[dict],
    source_mapping: dict[int, int | list[int] | None] | None,
    original_data: list[dict],
) -> None:
    """Give every output item a source_guid: inherit the parent's, else born at the producer.

    Mutates structured_data in place; an explicit tool value wins. A parent's only
    child inherits; every other row is born here, since one guid shared between
    distinct entities is one row to every store keyed by identity. Born rows are
    stored whole and take a correlation id derived from the one they inherited —
    distinct per row, equal across version branches.

    ``parent_source_guid`` is left as carried: #1046 freed the resolver, #1022 remains.
    """
    from agent_actions.utils.id_generation import IDGenerator

    inheriting = [i for i, item in enumerate(structured_data) if not item.get("source_guid")]
    parents = {
        i: _parent_index(i, structured_data, source_mapping, original_data) for i in inheriting
    }
    claimed: Counter[int] = Counter(idx for idx in parents.values() if idx is not None)

    for i in inheriting:
        item = structured_data[i]
        # Which inputs this row consumed, minus the one its own guid will carry. A
        # later run resolves those inputs from here; parent_source_guid cannot serve,
        # being the pool ancestor once an input was itself expanded.
        consumed = _consumed_guids(i, structured_data, source_mapping, original_data)
        source_idx = parents[i]
        parent = original_data[source_idx] if source_idx is not None else None
        parent_guid = parent.get("source_guid") if parent else None

        if parent is not None and parent_guid and claimed[cast(int, source_idx)] == 1:
            if parent.get("parent_source_guid") and not item.get("parent_source_guid"):
                item["parent_source_guid"] = parent["parent_source_guid"]
            item["source_guid"] = parent_guid
            _record_producers(item, consumed)
            continue

        # Hand on the parent's pool-resolvable identity, not the intermediate one:
        # a parent that is itself an expansion child has a minted guid matching
        # nothing in the source pool.
        if parent is not None:
            inherited = parent.get("parent_source_guid") or parent_guid
            if inherited and not item.get("parent_source_guid"):
                item["parent_source_guid"] = inherited
        item["source_guid"] = IDGenerator.generate_source_guid()
        _record_producers(item, consumed)
        # A minted guid joins nothing upstream, so the row has to carry its whole
        # content rather than be stored as a delta against it.
        item["_delta_mode"] = "full"
        # Distinct per row so a merge cannot fan them back into the one identity
        # they were just given; derived, so two version branches still correlate
        # and the pool keeps a key every record shares. A bare drop loses both.
        # Appended rather than replaced: chained aggregations grow it a segment
        # each, where replacing would collide this stage's rows with the last's.
        inherited_correlation = item.get("version_correlation_id")
        if inherited_correlation:
            item["version_correlation_id"] = f"{inherited_correlation}#{i}"


def _record_producers(item: dict[str, Any], consumed: list[str]) -> None:
    """Note the consumed inputs the row's own identity does not already account for."""
    producers = [guid for guid in consumed if guid != item.get("source_guid")]
    if producers:
        item["producer_source_guids"] = producers


def _resolve_input_record(
    input_idx: int | None, original_data: list[dict]
) -> dict[str, Any] | None:
    """Resolve the input record for namespace carry-forward.

    When *input_idx* is ``None`` (synthetic record), falls back to
    ``original_data[0]`` — all records in a batch share upstream namespaces.
    Raises ``IndexError`` when *input_idx* names no input position.
    """
    if not original_data:
        return None
    if input_idx is None:
        return original_data[0]
    if not is_input_position(input_idx, len(original_data)):
        raise IndexError(
            f"source_index {input_idx!r} does not name one of the {len(original_data)} input records"
        )
    return original_data[input_idx]


def extract_tool_input(record: dict, context_scope: Mapping[str, Any]) -> dict:
    """Extract observed business fields from an enriched record for tool input.

    Reads post-drop enriched content and plans keys through the same function
    enrichment uses, so the payload and the record agree. Names come from the
    observe refs alone, so they do not vary with the data. Flattens all content
    namespaces only when no ``observe`` key is declared — an explicit
    ``observe: []`` gates every business field, matching the prompt path.
    """
    from agent_actions.prompt.context.scope_application import (
        _resolve_observe_refs_for_flat_keys,
        plan_flat_observed_keys,
    )

    content = record.get("content")
    if not isinstance(content, dict):
        return {}

    if "observe" not in context_scope:
        # No observe directive at all — flatten every content namespace.
        # An explicit `observe: []` is a declared gate, not an absent key, and
        # falls through to the planning path below (which yields {}).
        business: dict = {}
        for ns_data in content.values():
            if isinstance(ns_data, dict):
                business.update(ns_data)
        return business

    # Drops and collision diagnostics were already handled by
    # apply_context_scope_for_records().
    resolved, qualify_wildcards = _resolve_observe_refs_for_flat_keys(
        context_scope["observe"], emit_diagnostics=False
    )
    flat, _ = plan_flat_observed_keys(content, resolved, qualify_wildcards)
    return flat


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


def reconcile_outputs(
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
    # None = no directive; [] = a declared gate. Collapsing them here would
    # reintroduce the truthiness bug this helper delegates past.
    context_scope: dict[str, Any] = {} if observe_refs is None else {"observe": observe_refs}
    return [
        TrackedItem(extract_tool_input(record, context_scope), source_index=i)
        for i, record in enumerate(records)
    ]


def framework_reconcile(
    raw_response: Any,
    action_name: str,
    original_data: list[dict],
) -> list[dict[str, Any]]:
    """Reconcile tool output to input records via provenance.

    Standalone wrapper over ``reconcile_outputs`` for design tests and
    simulations.
    """
    data, _ = reconcile_outputs(raw_response, action_name, original_data)
    return data


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


def is_empty_response(raw_response: Any) -> bool:
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
    *,
    agent_indices: dict[str, int] | None = None,
    source_data: list[dict[str, Any]] | None = None,
    is_first_stage: bool = False,
    version_context: dict[str, Any] | None = None,
    workflow_metadata: dict[str, Any] | None = None,
    dependency_configs: dict[str, Any] | None = None,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Evaluate guard per-record and split into passing, skipped, and filtered arrays.

    Called before FILE-mode processing to apply per-record guard logic
    on the full array.  ``behavior: filter`` records are excluded from
    both returned lists.  ``behavior: skip`` records land in *skipped*
    so the caller can merge them back into output with original content.

    When ``original_data`` is provided (e.g. pre-observe-filter records),
    the third return value contains the corresponding original items for
    each passing record.  This preserves upstream fields that observe
    filtering may have stripped.

    When pipeline context parameters are provided (agent_indices, source_data,
    etc.), guard evaluation uses full field_context — identical to
    TaskPreparer.prepare() — so guards referencing source, version, workflow,
    or promoted output_fields produce correct decisions.

    When no guard is configured, returns ``(data, [], original_data or data, [])``.

    Returns:
        (passing, skipped, original_passing, filtered)
    """
    originals = original_data if original_data is not None else data

    if original_data is not None and len(original_data) != len(data):
        raise RuntimeError(
            f"prefilter_by_guard received {len(original_data)} original_data for "
            f"{len(data)} input records — length mismatch"
        )

    guard_config = agent_config.get("guard")
    conditional_clause = agent_config.get("conditional_clause")
    if not guard_config and not conditional_clause:
        return data, [], originals, []

    from agent_actions.guards import GuardBehavior
    from agent_actions.input.preprocessing.filtering.evaluator import (
        get_guard_evaluator,
    )
    from agent_actions.processing.guard_context import build_guard_context
    from agent_actions.utils.content import get_existing_content

    evaluator = get_guard_evaluator()
    # The config expander normalizes user-facing "on_false" into "behavior"
    # conditional_clause (legacy UDF) always uses SKIP behavior; guard_config
    # may override via its "behavior" key.
    if guard_config:
        behavior = GuardBehavior(guard_config.get("behavior", "filter"))
    else:
        behavior = GuardBehavior.SKIP

    passing: list[dict] = []
    skipped: list[dict] = []
    original_passing: list[dict] = []
    filtered: list[dict] = []
    for idx, item in enumerate(data):
        eval_item = get_existing_content(item)

        context = build_guard_context(
            item,
            agent_name=agent_name,
            agent_config=agent_config,
            agent_indices=agent_indices,
            source_data=source_data,
            is_first_stage=is_first_stage,
            version_context=version_context,
            workflow_metadata=workflow_metadata,
            dependency_configs=dependency_configs,
        )

        result = evaluator.evaluate(
            item=eval_item,
            guard_config=guard_config,
            context=context,
            conditional_clause=conditional_clause,
        )

        if result.should_execute:
            passing.append(item)
            original_passing.append(originals[idx])
        elif behavior == GuardBehavior.SKIP:
            # Use pre-observe original so skipped tombstones keep namespaced content.
            skipped.append(originals[idx])
        else:
            # behavior == GuardBehavior.FILTER: use original for source_guid access.
            filtered.append(originals[idx])

    logger.info(
        "Guard pre-filter for '%s': %d passed, %d skipped, %d filtered of %d total",
        agent_name,
        len(passing),
        len(skipped),
        len(filtered),
        len(data),
    )

    return passing, skipped, original_passing, filtered
