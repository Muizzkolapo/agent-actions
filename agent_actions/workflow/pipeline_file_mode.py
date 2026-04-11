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
        # Get tools_path from agent config
        tools_path = context.agent_config.get("tools_path")

        # Invoke tool once with full array
        # For tools, formatted_prompt is not used, so we pass empty string
        raw_response, executed = run_dynamic_agent(
            agent_config=cast(dict[str, Any], context.agent_config),
            agent_name=context.agent_name,
            context=data,  # Full array of records
            formatted_prompt="",  # Not used for tools
            tools_path=tools_path,
        )

        # Safety net: unwrap FileUDFResult if it wasn't already unwrapped
        # during validation in _validate_udf_output. Handles the case where
        # validation is skipped (validate_output=False or no json_output_schema).
        from agent_actions.utils.udf_management.registry import FileUDFResult

        source_mapping = None
        if isinstance(raw_response, FileUDFResult):
            source_mapping = raw_response.source_mapping
            raw_response = raw_response.outputs

        # Tool should return array
        if not isinstance(raw_response, list):
            raise ValueError(
                f"FILE mode tool must return a list (or FileUDFResult), "
                f"got {type(raw_response).__name__}"
            )

        # Empty tool output with non-empty input → FAILED (see _MANIFEST.md)
        if not raw_response and data:
            return [
                ProcessingResult.failed(
                    error=(
                        f"Tool '{context.agent_name}' returned empty result "
                        f"from {len(data)} input record(s)"
                    ),
                )
            ]

        # Reserved framework fields that go at top level, not in content
        RESERVED_FIELDS = {
            "source_guid",
            "target_id",
            "node_id",
            "lineage",
            "metadata",
            "content",
        }

        # Wrap each tool output in {content: {...}} structure
        # Preserve source_guid at top level for lineage chaining
        structured_data = []
        for item in raw_response:
            if isinstance(item, dict):
                # Separate data fields from reserved framework fields
                data_fields = {k: v for k, v in item.items() if k not in RESERVED_FIELDS}

                # Build structured item with content
                structured_item = {"content": data_fields}

                # Preserve source_guid at top level (needed for lineage chaining)
                if "source_guid" in item:
                    structured_item["source_guid"] = item["source_guid"]

                structured_data.append(structured_item)
            else:
                # Handle non-dict outputs
                structured_data.append({"content": {"value": item}})

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
        structured_data = []
        if original_data:
            reserved_fields = {
                "source_guid",
                "target_id",
                "node_id",
                "lineage",
                "metadata",
                "content",
                "_unprocessed",
                "_recovery",
            }
            for idx, item in enumerate(original_data):
                if isinstance(item, dict):
                    if isinstance(item.get("content"), dict):
                        base_content = dict(item["content"])
                    else:
                        base_content = {
                            key: value for key, value in item.items() if key not in reserved_fields
                        }
                        raw_content = item.get("content")
                        if not base_content and raw_content is not None:
                            base_content = {"value": raw_content}
                else:
                    base_content = {"value": item}  # type: ignore[unreachable]

                merged_content = dict(base_content)
                merged_content.update(decision_common)
                if record_reviews and idx < len(record_reviews):
                    review_payload = record_reviews[idx]
                    if isinstance(review_payload, dict):
                        normalized_review_payload = {
                            key: value
                            for key, value in review_payload.items()
                            if key in {"hitl_status", "user_comment"}
                        }
                        merged_content.update(normalized_review_payload)
                structured_item = {"content": merged_content}
                if isinstance(item, dict):
                    for field in (
                        "source_guid",
                        "target_id",
                        "_unprocessed",
                        "_recovery",
                        "metadata",
                    ):
                        if field in item:
                            structured_item[field] = item[field]
                structured_data.append(structured_item)

        result = ProcessingResult(
            status=ProcessingStatus.SUCCESS,
            data=structured_data,
            source_guid=None,
            raw_response=raw_response,
            executed=executed,
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
) -> tuple[list[dict], list[dict]]:
    """Evaluate guard per-record and split into passing and skipped arrays.

    Called before FILE-mode processing to apply per-record guard logic
    on the full array.  ``behavior: filter`` records are excluded from
    both returned lists.  ``behavior: skip`` records land in *skipped*
    so the caller can merge them back into output with original content.

    When no guard is configured, returns ``(data, [])``.

    Returns:
        (passing, skipped)
    """
    guard_config = agent_config.get("guard")
    if not guard_config:
        return data, []

    from agent_actions.input.preprocessing.filtering.evaluator import get_guard_evaluator

    evaluator = get_guard_evaluator()
    # The config expander normalizes user-facing "on_false" into "behavior"
    behavior = str(guard_config.get("behavior", "filter")).lower()

    passing: list[dict] = []
    skipped: list[dict] = []
    for item in data:
        content = item.get("content", item)
        eval_item = content if isinstance(content, dict) else {"_raw": content}

        result = evaluator.evaluate_with_context(
            item=eval_item,
            guard_config=guard_config,
            context={},
            conditional_clause=None,
        )

        if result.should_execute:
            passing.append(item)
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

    return passing, skipped


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
        content = item.get("content", item) if isinstance(item.get("content"), dict) else item
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
