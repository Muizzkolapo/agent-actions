"""Unified record envelope -- single authority for record content assembly."""

from __future__ import annotations

from typing import Any

from agent_actions.record.state import (
    RecordState,
    RecordStateTransitionError,
    append_transition,
    parse_state_strict,
    validate_state_transition,
)

# Tracking fields: set once at record creation, carried forward through all 1:1
# pipeline stages by RecordEnvelope.build(). These are the record's stable identity.
RECORD_TRACKING_FIELDS: frozenset[str] = frozenset(
    {
        "source_guid",
        "version_correlation_id",
    }
)

# Per-stage fields: rebuilt by enrichers at each stage. NOT carried forward.
# parent_target_id and root_target_id are set by LineageEnricher from the
# parent's target_id — they're derived per-stage, not stable identity.
RECORD_STAGE_FIELDS: frozenset[str] = frozenset(
    {
        "target_id",
        "node_id",
        "lineage",
        "metadata",
        "content",
        "_state",
        "_transitions",
        "_recovery",
        "parent_target_id",
        "root_target_id",
        "chunk_info",
    }
)

# Union of all framework fields. Used by record_processor (first-stage source wrapping),
# pipeline_file_mode (tool input stripping), and scope_namespace (metadata exclusion).
RECORD_FRAMEWORK_FIELDS: frozenset[str] = RECORD_TRACKING_FIELDS | RECORD_STAGE_FIELDS


class RecordEnvelopeError(Exception):
    """Raised when a record envelope contract is violated."""

    pass


class RecordEnvelope:
    """Single authority for record content assembly."""

    @staticmethod
    def build(
        action_name: str,
        action_output: dict[str, Any],
        input_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a record wrapping *action_output* under *action_name*.

        Preserves upstream namespaces from *input_record* and carries
        ``source_guid``.  Collision on *action_name* overwrites.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required")
        if not isinstance(action_output, dict):
            raise RecordEnvelopeError(
                f"action_output must be a dict, got {type(action_output).__name__} "
                f"for action '{action_name}'"
            )

        existing = _extract_existing(input_record)
        result: dict[str, Any] = {
            "content": {**existing, action_name: action_output},
            "_state": RecordState.ACTIVE.value,
        }
        return _carry_tracking_fields(result, input_record)

    @staticmethod
    def build_content(
        action_name: str,
        action_output: dict[str, Any],
        existing_content: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a content dict with *action_output* under *action_name*.

        No record wrapper or ``source_guid`` -- content level only.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required")
        content = dict(existing_content) if existing_content else {}
        content[action_name] = action_output
        return content

    @staticmethod
    def build_skipped(
        action_name: str,
        input_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a record with a null namespace for a guard-skipped action.

        Does NOT set execution metadata; callers may add framework fields.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required")
        existing = _extract_existing(input_record)
        result: dict[str, Any] = {
            "content": {**existing, action_name: None},
            "_state": RecordState.ACTIVE.value,
        }
        return _carry_tracking_fields(result, input_record)

    @staticmethod
    def transition(
        record: dict[str, Any],
        new_state: RecordState,
        *,
        action_name: str,
        reason: dict[str, Any],
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Transition a record to a new state and record the transition.

        This is the only supported way to mutate `_state`.
        """
        try:
            prior = parse_state_strict(record)
            validate_state_transition(prior, new_state, reason)
        except RecordStateTransitionError as e:
            raise RecordEnvelopeError(str(e)) from e
        record["_state"] = new_state.value
        append_transition(
            record,
            action=action_name,
            from_state=prior,
            to_state=new_state,
            reason=reason,
            detail=detail,
        )
        return record


def _carry_tracking_fields(
    result: dict[str, Any], input_record: dict[str, Any] | None
) -> dict[str, Any]:
    """Copy tracking fields from input_record to result.

    Tracking fields are the record's stable identity — set once at creation
    (first stage or 1→N expansion) and preserved through all downstream
    1:1 stages. Per-stage fields (metadata, lineage, node_id, etc.) are
    NOT carried — enrichers rebuild those.
    """
    if not input_record:
        return result
    for field in RECORD_TRACKING_FIELDS:
        if field in input_record:
            result[field] = input_record[field]
    return result


def _extract_existing(input_record: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the existing content dict from an input record."""
    if input_record is None:
        return {}
    content = input_record.get("content")
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise RecordEnvelopeError(
            f"input_record['content'] must be a dict, got {type(content).__name__}"
        )
    return content
