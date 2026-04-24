"""FILE-granularity processing handlers extracted from ProcessingPipeline.

These standalone functions handle tool and HITL processing when granularity
is ``file`` — i.e. the entire input array is passed as one unit rather than
looping per-record.
"""

from __future__ import annotations

import logging
import warnings
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from agent_actions.config.types import ActionConfigDict
from agent_actions.errors import AgentActionsError
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events.io_events import ContextFieldSkippedEvent
from agent_actions.processing.helpers import run_dynamic_agent
from agent_actions.processing.types import (
    ProcessingContext,
    ProcessingResult,
    ProcessingStatus,
)
from agent_actions.prompt.context.scope_parsing import parse_field_reference

if TYPE_CHECKING:
    from agent_actions.workflow.pipeline import ProcessingPipeline

logger = logging.getLogger(__name__)


# Framework fields that live at the top level of structured records, not inside content.
_TOOL_RESERVED_FIELDS = frozenset(
    {
        "source_guid",
        "target_id",
        "node_id",
        "lineage",
        "metadata",
        "content",
        "parent_target_id",
        "root_target_id",
        "chunk_info",
        "_recovery",
        "_unprocessed",
    }
)


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
    source_mapping: dict[int, int | list[int]] | None,
    original_data: list[dict],
) -> None:
    """Reattach source_guid from input records to output items using mapping.

    Mutates structured_data in place.  Only sets source_guid when the output
    item does not already carry a truthy value (explicit tool values win).
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
                source_idx: int | list[int] = i
            else:
                continue  # Unmapped output — new record, no parent to inherit from
        else:
            source_idx = source_mapping[i]
        if isinstance(source_idx, list):
            source_idx = source_idx[0]  # Many-to-one: use first parent

        if isinstance(source_idx, int) and source_idx < len(original_data):
            parent_guid = original_data[source_idx].get("source_guid")
            if parent_guid:
                item["source_guid"] = parent_guid


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_file_mode_tool(
    pipeline: ProcessingPipeline,
    data: list[dict],
    original_data: list[dict],
    context: ProcessingContext,
) -> list:
    """Process tool in FILE granularity mode.

    Invokes tool once with full array instead of looping per-record.
    Tool receives array WITH existing IDs/lineage.
    Tool returns array of outputs (N→M transformation allowed).
    Enrichment assigns new IDs/lineage to each output.

    Args:
        pipeline: The parent ``ProcessingPipeline`` instance.
        data: Observe-filtered records (passed to tool).
        original_data: Unfiltered records (available for enrichment).
        context: Processing context.

    Returns:
        List with single ProcessingResult containing all outputs.
    """
    try:
        tools_path = context.agent_config.get("tools_path")

        raw_response, executed = run_dynamic_agent(
            agent_config=cast(dict[str, Any], context.agent_config),
            agent_name=context.agent_name,
            context=data,
            formatted_prompt="",
            tools_path=tools_path,
        )

        from agent_actions.utils.udf_management.registry import FileUDFResult

        if isinstance(raw_response, FileUDFResult):
            raw_response = raw_response.outputs

        if not isinstance(raw_response, list):
            raise ValueError(
                f"FILE mode tool must return a list (or FileUDFResult), "
                f"got {type(raw_response).__name__}"
            )

        if not raw_response and data:
            return [
                ProcessingResult.failed(
                    error=(
                        f"Tool '{context.agent_name}' returned empty result "
                        f"from {len(data)} input record(s)"
                    ),
                )
            ]

        # Framework-managed: resolve which input produced each output by node_id.
        source_mapping: dict[int, int | list[int]] | None = None
        if original_data:
            source_mapping = _resolve_source_mapping(
                raw_outputs=raw_response,
                input_data=original_data,
                action_name=context.agent_name,
            )

        # Separate business data from framework fields in tool output.
        # Additive model: wrap tool output under action namespace, preserve
        # existing namespaces from the input record.
        # Version merge: version namespaces are already the correct additive
        # format — spread instead of wrapping under the action name.
        from agent_actions.record.envelope import RecordEnvelope
        from agent_actions.utils.content import get_existing_content, is_version_merge

        version_merge = is_version_merge(context.agent_config)

        structured_data = []
        for idx, item in enumerate(raw_response):
            if isinstance(item, dict):
                if isinstance(item.get("content"), dict):
                    data_fields = item["content"]
                else:
                    data_fields = {k: v for k, v in item.items() if k not in _TOOL_RESERVED_FIELDS}

                # Resolve the input record for namespace carry-forward.
                # For N→M tools (dedup, filter), source_mapping may not resolve.
                # Fall back to the first input record — all records in a FILE
                # batch share the same upstream namespaces.
                input_idx = source_mapping.get(idx) if source_mapping else None
                if isinstance(input_idx, list):
                    input_idx = input_idx[0]
                input_record: dict[str, Any] | None = None
                if isinstance(input_idx, int) and input_idx < len(original_data):
                    input_record = original_data[input_idx]
                elif original_data:
                    input_record = original_data[0]

                if version_merge:
                    # build_version_merge validates all values are dicts,
                    # but version merge tools return flat business data
                    # (strings, ints) to spread alongside version namespaces.
                    existing = get_existing_content(input_record) if input_record else {}
                    record: dict[str, Any] = {"content": {**existing, **data_fields}}
                else:
                    record = RecordEnvelope.build(context.agent_name, data_fields, input_record)

                # Source_guid is managed by _reattach_source_guid below, not
                # RecordEnvelope.  Remove it here so the existing handling
                # works: tool explicit value first, then mapping-based.
                record.pop("source_guid", None)

                if "source_guid" in item:
                    record["source_guid"] = item["source_guid"]

                structured_data.append(record)
            else:
                structured_data.append(RecordEnvelope.build(context.agent_name, {"value": item}))

        # Reattach source_guid from input records — authoritative for FILE mode.
        # LineageBuilder._propagate_ancestry_chain and RequiredFieldsEnricher
        # also set source_guid but are idempotent backstops; this is the primary setter.
        _reattach_source_guid(structured_data, source_mapping, original_data)

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
        # NOTE: Intentional behavioral change — FILE mode tool errors now raise
        # instead of returning FAILED silently. Workflows relying on partial-failure
        # tolerance should use try/except or error handling at the caller level.
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

    from agent_actions.input.preprocessing.filtering.evaluator import get_guard_evaluator

    evaluator = get_guard_evaluator()
    # The config expander normalizes user-facing "on_false" into "behavior"
    behavior = str(guard_config.get("behavior", "filter")).lower()

    passing: list[dict] = []
    skipped: list[dict] = []
    original_passing: list[dict] = []
    for idx, item in enumerate(data):
        content = item.get("content", item)
        eval_item = content if isinstance(content, dict) else {"_raw": content}

        # context={} — see Note in docstring.
        result = evaluator.evaluate_with_context(
            item=eval_item,
            guard_config=guard_config,
            context={},
            conditional_clause=None,
        )

        if result.should_execute:
            passing.append(item)
            original_passing.append(originals[idx])
        elif behavior == "skip":
            skipped.append(item)
        # behavior == "filter": record excluded from both lists

    logger.info(
        "Guard pre-filter for '%s': %d passed, %d skipped, %d filtered of %d total",
        agent_name,
        len(passing),
        len(skipped),
        len(data) - len(passing) - len(skipped),
        len(data),
    )

    return passing, skipped, original_passing


def apply_observe_filter(data: list[dict], agent_config: ActionConfigDict) -> list[dict]:
    """Filter records to context_scope.observe fields in defined order.

    Returns filtered copy; original data is unchanged.
    If no observe is configured, returns data as-is.

    .. deprecated::
        Use ``apply_observe_for_file_mode`` instead.
        This method strips namespaces and performs bare-key lookup only,
        which silently fails for cross-namespace references.
    """
    warnings.warn(
        "_apply_observe_filter is deprecated. Use apply_observe_for_file_mode instead.",
        DeprecationWarning,
        stacklevel=3,  # caller → delegator stub → this function
    )
    context_scope = agent_config.get("context_scope") or {}
    observe_refs = context_scope.get("observe")
    if not observe_refs:
        return data

    # Parse refs in lockstep so invalid entries don't misalign the two lists.
    valid_pairs = []  # [(original_ref, bare_field_name), ...]
    for ref in observe_refs:
        try:
            _, field_name = parse_field_reference(ref)
            valid_pairs.append((ref, field_name))
        except ValueError as e:
            fire_event(
                ContextFieldSkippedEvent(
                    action_name=agent_config.get("name", "unknown"),
                    field_ref=ref,
                    reason=str(e),
                    directive="observe_filter",
                )
            )
            continue

    if not valid_pairs:
        return data

    # Wildcard or prefix pattern → no filtering needed
    if any(bare in ("*", "_") for _, bare in valid_pairs):
        return data

    # Detect bare-key collisions so we can namespace them.
    # e.g. ["dep_a.title", "dep_b.title", "dep_a.body"] → collisions = {"title"}
    from collections import Counter

    bare_counts = Counter(bare for _, bare in valid_pairs)
    collisions = {k for k, v in bare_counts.items() if v > 1}

    # Build (output_key, bare_key) pairs preserving observe order.
    # Colliding bare keys use the full qualified ref as the output key;
    # unique bare keys stay bare for backwards compatibility.
    key_pairs = []  # [(output_key, bare_key), ...]
    for ref, bare in valid_pairs:
        output_key = ref if bare in collisions else bare
        key_pairs.append((output_key, bare))

    filtered = []
    for item in data:
        if not isinstance(item, dict):
            filtered.append(item)  # type: ignore[unreachable]
            continue
        content_val = item.get("content")
        content = (
            content_val
            if isinstance(content_val, dict) and content_val
            else {k: v for k, v in item.items() if k not in _TOOL_RESERVED_FIELDS}
        )
        ordered = {ok: content[bk] for ok, bk in key_pairs if bk in content}
        missing = [bk for _, bk in key_pairs if bk not in content]
        if missing:
            logger.warning(
                "[OBSERVE FILTER] Fields %s not found in record. "
                "Available: %s. Check that observe field names match the actual data.",
                list(set(missing)),
                list(content.keys()),
            )
        filtered.append(ordered)
    return filtered
