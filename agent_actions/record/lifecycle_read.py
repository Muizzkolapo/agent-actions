"""Fail-closed lifecycle validation for records loaded from target storage.

Any record loaded from a frozen target directory as upstream input for a
downstream action must carry ``_state``.  Missing ``_state`` means the
record pre-dates the lifecycle machine or was written outside
``RecordEnvelope.transition()`` — both are unrecoverable without a re-run.

There is no migration path: delete ``agent_io/target/`` and re-run from
the beginning.  See ``record/_MANIFEST.md`` for the transition rules.
"""

from __future__ import annotations

from typing import Any

from agent_actions.errors.configuration import ConfigurationError
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.record.state import RESETTABLE_DOWNSTREAM_STATES, RecordState

_SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})
_VALID_STATES: frozenset[str] = frozenset(s.value for s in RecordState)


def validate_lifecycle(
    record: dict[str, Any],
    *,
    action_name: str,
) -> None:
    """Raise ``ConfigurationError`` if *record* is missing a valid lifecycle state.

    Call this immediately after loading a record from target storage as
    upstream input.  Never call it on staging/source records — those do not
    carry ``_state``.

    Raises ``ConfigurationError`` with an actionable message that names the
    offending action and record id so the operator knows exactly what to
    delete and re-run.
    """
    source_guid = record.get("source_guid", "?")

    if "_state" not in record:
        raise ConfigurationError(
            f"Record is missing '_state'. Delete agent_io/target/ and re-run. "
            f"(action='{action_name}', source_guid='{source_guid}')"
        )

    raw_state = record["_state"]
    if raw_state not in _VALID_STATES:
        raise ConfigurationError(
            f"Record has unrecognised '_state' value {raw_state!r}. "
            f"Delete agent_io/target/ and re-run. "
            f"(action='{action_name}', source_guid='{source_guid}')"
        )

    schema_version = record.get("_state_schema_version")
    if schema_version is not None and schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise ConfigurationError(
            f"Record has unsupported '_state_schema_version' {schema_version!r}. "
            f"Supported: {sorted(_SUPPORTED_SCHEMA_VERSIONS)}. "
            f"Delete agent_io/target/ and re-run. "
            f"(action='{action_name}', source_guid='{source_guid}')"
        )


def validate_lifecycle_batch(
    records: list[dict[str, Any]],
    *,
    action_name: str,
) -> None:
    """Validate lifecycle state for every record in *records*.

    Fails on the first invalid record.  Use this after loading a full
    target file from storage.
    """
    for i, record in enumerate(records):
        if not isinstance(record, dict):
            raise ConfigurationError(
                f"Expected a dict at index {i} in target data for action '{action_name}', "
                f"got {type(record).__name__}. Delete agent_io/target/ and re-run."
            )
        validate_lifecycle(record, action_name=action_name)


_RESETTABLE_VALUES: frozenset[str] = frozenset(s.value for s in RESETTABLE_DOWNSTREAM_STATES)


def reset_for_downstream(
    records: list[dict[str, Any]],
    *,
    action_name: str,
) -> None:
    """Reset resettable records to ACTIVE for downstream processing.

    Records in RESETTABLE_DOWNSTREAM_STATES (PROCESSED, GUARD_SKIPPED)
    are reset to ACTIVE via transition().
    Records in CASCADE_BLOCKING_STATES stay as-is for cascade logic.
    ACTIVE records pass through unchanged.
    """
    for record in records:
        raw_state = record.get("_state")
        if raw_state in _RESETTABLE_VALUES:
            RecordEnvelope.transition(record, RecordState.ACTIVE, action_name, "downstream_reset")
