"""Shared record assembly helpers — used by all processing paths.

Centralises tombstone construction, version-merge content assembly,
framework-field carry-forward, and existing-content extraction so that
every processing path (online, batch, FILE) behaves identically.
"""

from __future__ import annotations

from typing import Any

from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS, RecordEnvelope
from agent_actions.record.state import RecordState, reason_error, reason_exhausted, reason_guard
from agent_actions.utils.content import get_existing_content, is_version_merge

# Framework fields that should be carried from an input record to an output
# record when the envelope builder does not manage them automatically.
CARRY_FORWARD_FIELDS: tuple[str, ...] = (
    "target_id",
    "_recovery",
    "metadata",
    "_state",
    "_transitions",
)


def build_guard_skipped_record(
    action_name: str,
    input_record: dict[str, Any] | None,
    *,
    source_guid: str | None = None,
    clause: str = "",
    behavior: str = "skip",
    result: bool = False,
    values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a guard-skipped passthrough record (null namespace + state)."""
    item = RecordEnvelope.build_skipped(action_name, input_record)
    if source_guid is not None:
        item["source_guid"] = source_guid
    RecordEnvelope.transition(
        item,
        RecordState.GUARD_SKIPPED,
        action_name=action_name,
        reason=reason_guard(clause=clause, behavior=behavior, result=result, values=values),
    )
    carry_framework_fields(input_record, item, fields=("target_id",))
    return item


def build_cascade_skipped_record(
    action_name: str,
    input_record: dict[str, Any] | None,
    *,
    source_guid: str | None = None,
    upstream_action: str | None = None,
    upstream_state: str | None = None,
    upstream_reason: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a cascade-skipped passthrough record (null namespace + state)."""
    item = RecordEnvelope.build_skipped(action_name, input_record)
    if source_guid is not None:
        item["source_guid"] = source_guid
    reason: dict[str, Any] = {"type": "cascade"}
    if upstream_action is not None:
        reason["upstream_action"] = upstream_action
    if upstream_state is not None:
        reason["upstream_state"] = upstream_state
    if upstream_reason is not None:
        reason["upstream_reason"] = upstream_reason
    RecordEnvelope.transition(
        item, RecordState.CASCADE_SKIPPED, action_name=action_name, reason=reason
    )
    carry_framework_fields(input_record, item, fields=("target_id",))
    return item


def build_failed_record(
    action_name: str,
    input_record: dict[str, Any] | None,
    *,
    source_guid: str | None = None,
    error_type: str,
    message: str,
) -> dict[str, Any]:
    """Build a failed passthrough record (null namespace + FAILED state)."""
    item = RecordEnvelope.build_skipped(action_name, input_record)
    if source_guid is not None:
        item["source_guid"] = source_guid
    RecordEnvelope.transition(
        item,
        RecordState.FAILED,
        action_name=action_name,
        reason=reason_error(error_type=error_type, message=message),
    )
    carry_framework_fields(input_record, item, fields=("target_id",))
    return item


def build_exhausted_tombstone(
    action_name: str,
    input_record: dict[str, Any] | None,
    empty_content: dict[str, Any],
    *,
    source_guid: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an exhausted-retry tombstone that preserves existing content.

    Unlike :func:`build_tombstone`, exhausted records need to carry
    the existing content (upstream namespaces) merged with an empty
    action output so downstream can see what was accumulated before
    exhaustion.
    """
    existing = get_existing_content(input_record) if input_record else {}
    content = RecordEnvelope.build_content(action_name, empty_content, existing)
    item: dict[str, Any] = {
        "content": content,
        "source_guid": source_guid,
        "_state": RecordState.ACTIVE.value,
    }
    retry_attempts = "unknown"
    last_error = None
    model = None
    if extra_metadata:
        # Some call sites already have structured retry metadata here; surface
        # common fields into the transition reason.
        retry_attempts = extra_metadata.get("attempts", retry_attempts)
        last_error = extra_metadata.get("last_error")
        model = extra_metadata.get("model")
    carry_framework_fields(input_record, item, fields=("target_id",))
    RecordEnvelope.transition(
        item,
        RecordState.EXHAUSTED,
        action_name=action_name,
        reason=reason_exhausted(attempts=retry_attempts, last_error=last_error, model=model),
    )
    return item


def carry_framework_fields(
    source: dict[str, Any] | None,
    target: dict[str, Any],
    *,
    fields: tuple[str, ...] = CARRY_FORWARD_FIELDS,
) -> dict[str, Any]:
    """Copy framework fields from *source* to *target* when present.

    Copies unconditionally when the field exists in *source* — callers
    that need to protect explicit values should pass a restricted
    *fields* tuple (e.g. ``fields=("target_id",)``).

    Returns *target* for convenience (mutates in-place).
    """
    if source is None or not isinstance(source, dict):
        return target
    for field in fields:
        if field in source:
            target[field] = source[field]
    return target


def apply_version_merge(
    agent_config: dict[str, Any],
    action_output: dict[str, Any],
    existing_content: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build content dict applying version-merge spread when appropriate.

    Version-merge spread (flat merge of existing + new) only applies to
    **tool** actions with ``version_consumption_config``.  LLM actions
    produce their own namespaced output even when consuming versions.

    Returns a content dict (not a full record envelope).
    """
    is_tool = agent_config.get("kind") == "tool"
    if is_version_merge(agent_config) and is_tool:
        return {**(existing_content or {}), **action_output}
    action_name = agent_config["action_name"]
    return RecordEnvelope.build_content(action_name, action_output, existing_content)


def extract_existing_content(
    record: dict[str, Any],
    *,
    is_first_stage: bool = False,
) -> dict[str, Any]:
    """Extract existing content with consistent first-stage fallback.

    On first-stage records that have no ``content`` dict, the raw
    non-framework fields are wrapped under ``{"source": ...}`` so
    downstream actions can reference source data.
    """
    existing = get_existing_content(record)
    if not existing and is_first_stage:
        raw = {k: v for k, v in record.items() if k not in RECORD_FRAMEWORK_FIELDS}
        if raw:
            return {"source": raw}
    return existing
