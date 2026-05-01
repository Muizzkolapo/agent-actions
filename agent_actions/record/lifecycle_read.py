"""Fail-closed validation for records loaded from frozen target storage."""

from __future__ import annotations

from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.record.state import (
    SUPPORTED_STATE_SCHEMA_VERSIONS,
    RecordState,
)


def require_frozen_record_lifecycle(
    record: dict[str, Any],
    *,
    action_name: str,
) -> None:
    """Require lifecycle fields present on a dict loaded as upstream/target input.

    Raises:
        ConfigurationError: If ``_state`` / ``_state_schema_version`` are missing,
            the schema version is unsupported, or ``_state`` is not a known
            :class:`RecordState` value.
    """
    if "_state" not in record:
        sid = record.get("source_guid", "?")
        raise ConfigurationError(
            f"Record missing '_state' field. Delete agent_io/target/ and re-run. "
            f"(action '{action_name}', source_guid '{sid}')",
            context={"action_name": action_name, "source_guid": sid},
        )
    if "_state_schema_version" not in record:
        sid = record.get("source_guid", "?")
        raise ConfigurationError(
            f"Record missing '_state_schema_version' field. Delete agent_io/target/ "
            f"and re-run. (action '{action_name}', source_guid '{sid}')",
            context={"action_name": action_name, "source_guid": sid},
        )
    raw_ver = record["_state_schema_version"]
    if raw_ver not in SUPPORTED_STATE_SCHEMA_VERSIONS:
        sid = record.get("source_guid", "?")
        supported = sorted(SUPPORTED_STATE_SCHEMA_VERSIONS)
        raise ConfigurationError(
            f"Unsupported _state_schema_version {raw_ver!r} (supported: {supported}). "
            f"Delete agent_io/target/ and re-run. (action '{action_name}', source_guid '{sid}')",
            context={
                "action_name": action_name,
                "source_guid": sid,
                "_state_schema_version": raw_ver,
            },
        )
    try:
        RecordState(record["_state"])
    except ValueError:
        sid = record.get("source_guid", "?")
        raise ConfigurationError(
            f"Record has unknown _state value {record['_state']!r}. "
            f"(action '{action_name}', source_guid '{sid}')",
            context={"action_name": action_name, "source_guid": sid},
        ) from None


def validate_frozen_target_payload(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    action_name: str,
) -> None:
    """Validate every dict in a target payload (list or single dict)."""
    if isinstance(data, dict):
        require_frozen_record_lifecycle(data, action_name=action_name)
        return
    for item in data:
        if isinstance(item, dict):
            require_frozen_record_lifecycle(item, action_name=action_name)
