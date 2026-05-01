"""Unified record envelope -- single authority for record content assembly.

``RecordEnvelope.transition()`` is the **only** sanctioned mutator for
lifecycle fields (``_state``, ``_state_history``, ``_state_schema_version``).
All other code reads these fields; it does not write them directly.

## _state_schema_version bump rules

Version 1 (current): history entries have keys
  {timestamp, action, from, to, reason, detail}

Bump to version 2 when: a new required key is added to history entries,
or the semantics of an existing key change in a breaking way.  Additive
optional keys do not require a bump.

## _state_history cap

History is capped at ``STATE_HISTORY_CAP`` entries (default: 64).  This
prevents unbounded serialization growth across long retry chains.  When the
cap is reached, the oldest entry is dropped on each new append.  64 entries
is enough for any realistic pipeline run (typical records see 2-10
transitions).
"""

from __future__ import annotations

import datetime
from typing import Any

from agent_actions.record.state import (
    PROCESSABLE_STATES,
    RESETTABLE_DOWNSTREAM_STATES,
    RecordState,
)

STATE_HISTORY_CAP: int = 64
_STATE_SCHEMA_VERSION: int = 1

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
        "_unprocessed",
        "_recovery",
        "parent_target_id",
        "root_target_id",
        "chunk_info",
        "_state",
        "_state_history",
        "_state_schema_version",
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

        The assembled content dict is new, but *action_output* itself is stored
        by reference inside it.  Callers must not mutate *action_output* after
        calling ``build()``.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required")
        if not isinstance(action_output, dict):
            raise RecordEnvelopeError(
                f"action_output must be a dict, got {type(action_output).__name__} "
                f"for action '{action_name}'"
            )

        existing = _extract_existing(input_record)
        result: dict[str, Any] = {"content": {**existing, action_name: action_output}}
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
        content = dict(existing_content) if existing_content is not None else {}
        content[action_name] = action_output
        return content

    @staticmethod
    def build_skipped(
        action_name: str,
        input_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a record with a null namespace for a guard-skipped action.

        Does NOT set ``_unprocessed`` or ``metadata`` -- callers add those.
        """
        if not action_name:
            raise RecordEnvelopeError("action_name is required")
        existing = _extract_existing(input_record)
        result: dict[str, Any] = {"content": {**existing, action_name: None}}
        return _carry_tracking_fields(result, input_record)

    @staticmethod
    def transition(
        record: dict[str, Any],
        to_state: RecordState,
        action_name: str,
        reason: str,
        detail: str | None = None,
    ) -> dict[str, Any]:
        """Transition *record* to *to_state* — the only sanctioned lifecycle mutator.

        Updates ``_state``, appends to ``_state_history`` (capped at
        ``STATE_HISTORY_CAP``), and sets ``_state_schema_version``.

        Raises ``RecordEnvelopeError`` if the transition is illegal.
        Returns the record (mutated in-place) for chaining.
        """
        from_state_raw = record.get("_state")
        from_state = RecordState(from_state_raw) if from_state_raw is not None else None

        _validate_transition(from_state, to_state)

        history: list[dict[str, Any]] = record.get("_state_history") or []
        entry: dict[str, Any] = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "action": action_name,
            "from": from_state_raw,
            "to": to_state.value,
            "reason": reason,
            "detail": detail,
        }
        history.append(entry)
        if len(history) > STATE_HISTORY_CAP:
            history = history[-STATE_HISTORY_CAP:]

        record["_state"] = to_state.value
        record["_state_history"] = history
        record["_state_schema_version"] = _STATE_SCHEMA_VERSION
        return record


def _validate_transition(from_state: RecordState | None, to_state: RecordState) -> None:
    """Raise RecordEnvelopeError if the from→to edge violates state machine rules."""
    if from_state is None:
        return
    if from_state == to_state:
        return
    if from_state in PROCESSABLE_STATES:
        return
    if from_state in RESETTABLE_DOWNSTREAM_STATES and to_state in PROCESSABLE_STATES:
        return
    raise RecordEnvelopeError(
        f"Illegal state transition: {from_state.value!r} → {to_state.value!r}"
    )


def _carry_tracking_fields(
    result: dict[str, Any], input_record: dict[str, Any] | None
) -> dict[str, Any]:
    """Copy tracking fields from input_record to result.

    Tracking fields are the record's stable identity — set once at creation
    (first stage or 1→N expansion) and preserved through all downstream
    1:1 stages. Per-stage fields (metadata, lineage, node_id, etc.) are
    NOT carried — enrichers rebuild those.
    """
    if input_record is None:
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
