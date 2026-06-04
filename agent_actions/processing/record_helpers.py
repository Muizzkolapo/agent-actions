"""Shared record assembly helpers — used by all processing paths.

Centralises tombstone construction, version-merge content assembly,
framework-field carry-forward, and existing-content extraction so that
every processing path (online, batch, FILE) behaves identically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.reasons import RETRY_EXHAUSTED
from agent_actions.utils.content import is_version_merge


def derive_relative_path(file_path: str | None, output_directory: str | None) -> str | None:
    """Derive relative storage key from file_path and output_directory.

    Mirrors FileWriter.write_target() path resolution: if output_directory
    is set, compute the relative path from it.  Falls back to filename-only.
    Returns None if file_path is not set.
    """
    if not file_path:
        return None
    p = Path(file_path)
    if output_directory:
        try:
            return str(p.relative_to(output_directory))
        except ValueError:
            pass
    return p.name


# Framework fields carried from input to output when the envelope builder
# does not manage them automatically.
# _state is intentionally absent — it resets per-action at the executor boundary.
# _state_history: carried by RecordEnvelope.build*() via RECORD_LIFECYCLE_FIELDS
# to preserve cumulative state transitions on tombstone records.
CARRY_FORWARD_FIELDS: tuple[str, ...] = (
    "target_id",
    "_recovery",
    "metadata",
)


def build_tombstone(
    action_name: str,
    input_record: dict[str, Any] | None,
    reason: str,
    *,
    source_guid: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a tombstone record for guard-skipped or unprocessed records.

    Uses :meth:`RecordEnvelope.build_skipped` to add a null namespace
    marker (``action_name: None``) while preserving upstream content.

    Always sets ``metadata.reason`` and ``metadata.agent_type = "tombstone"``.
    Carries ``target_id`` from *input_record*.

    For retry-exhausted records that need empty content under the
    namespace (not null), use :func:`build_exhausted_tombstone` instead.
    """
    item = RecordEnvelope.build_skipped(action_name, input_record)
    item["source_guid"] = source_guid
    item["metadata"] = {"reason": reason, "agent_type": "tombstone"}
    if extra_metadata:
        item["metadata"].update(extra_metadata)
    item["_tombstone"] = True
    item["_tombstone_reason"] = reason
    carry_framework_fields(input_record, item, fields=("target_id",))
    return item


def build_exhausted_tombstone(
    action_name: str,
    input_record: dict[str, Any] | None,
    empty_content: dict[str, Any],
    *,
    source_guid: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
    reason: str = RETRY_EXHAUSTED,
) -> dict[str, Any]:
    """Build an exhausted tombstone that preserves existing content.

    Unlike :func:`build_tombstone`, exhausted records need to carry
    the existing content (upstream namespaces) merged with an empty
    action output so downstream can see what was accumulated before
    exhaustion.

    Routes through :meth:`RecordEnvelope.build` so lifecycle fields
    (``_state_history``, ``_state_schema_version``) are carried automatically.
    """
    item = RecordEnvelope.build(action_name, empty_content, input_record)
    item["source_guid"] = source_guid
    item["metadata"] = {
        "reason": reason,
        "retry_exhausted": True,
        "agent_type": "tombstone",
    }
    if extra_metadata:
        item["metadata"].update(extra_metadata)
    item["_tombstone"] = True
    item["_tombstone_reason"] = reason
    carry_framework_fields(input_record, item, fields=("target_id",))
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
            value = source[field]
            # Shallow-copy lists to prevent aliasing (transition()
            # appends in-place to _state_history).
            if isinstance(value, list):
                value = list(value)
            target[field] = value
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
