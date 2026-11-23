"""Stored recovery state that names a type or phase this version does not know must
refuse, not vanish. Dropping it makes the parent batch look unsubmitted, so the next
run pays for it again."""

from __future__ import annotations

import json

import pytest

from agent_actions.errors import is_action_fatal
from agent_actions.llm.batch.core.batch_constants import (
    RecoveryPhase,
    RecoveryType,
    UnknownRecoveryState,
)
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

ACTION = "my_action"
PARENT = "my_action_batch"
CHILD = "my_action_made_up_1"
UNKNOWN = "made_up"


class _Metadata:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value


def _entry_dict(recovery_type: str) -> dict:
    return {
        "batch_id": "batch-child-1",
        "status": "completed",
        "timestamp": "2026-09-01T09:01:00Z",
        "provider": "openai",
        "file_name": CHILD,
        "parent_file_name": PARENT,
        "recovery_type": recovery_type,
        "recovery_attempt": 1,
    }


def _registry_with(child: dict) -> _Metadata:
    parent = BatchJobEntry(
        batch_id="batch-parent",
        status="completed",
        timestamp="2026-09-01T09:00:00Z",
        provider="openai",
        file_name=PARENT,
    )
    backend = _Metadata()
    backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = json.dumps(
        {PARENT: parent.to_dict(), CHILD: child}
    )
    return backend


def _assert_refusal(error: UnknownRecoveryState) -> str:
    message = str(error)
    assert UNKNOWN in message, f"the refusal must name the value, got: {message}"
    assert "--fresh" in message, f"the refusal must say what to do, got: {message}"
    assert is_action_fatal(error), "--fresh is the action's remedy, not one file's"
    return message


@pytest.mark.parametrize("recovery_type", list(RecoveryType), ids=str)
def test_every_known_recovery_type_loads(recovery_type):
    entry = BatchJobEntry.from_dict(_entry_dict(recovery_type.value))
    assert entry.recovery_type is recovery_type


@pytest.mark.parametrize("phase", list(RecoveryPhase), ids=str)
def test_every_known_recovery_phase_loads(phase):
    assert RecoveryState(phase=phase.value).phase is phase


def test_an_unknown_recovery_type_is_refused():
    with pytest.raises(UnknownRecoveryState) as raised:
        BatchJobEntry.from_dict(_entry_dict(UNKNOWN))
    _assert_refusal(raised.value)


def test_an_unknown_recovery_phase_is_refused():
    with pytest.raises(UnknownRecoveryState) as raised:
        RecoveryState(phase=UNKNOWN)
    _assert_refusal(raised.value)


def test_the_registry_refusal_names_the_action_and_the_entry():
    """`agac batch` sweeps every action's registry, so the refusal must say which one."""
    manager = BatchRegistryManager(_registry_with(_entry_dict(UNKNOWN)), ACTION)

    with pytest.raises(UnknownRecoveryState) as raised:
        manager.get_all_jobs()

    message = _assert_refusal(raised.value)
    assert ACTION in message, f"the refusal must name the action, got: {message}"
    assert CHILD in message, f"the refusal must name the entry, got: {message}"


def test_the_stored_state_refusal_names_the_action_and_the_file():
    backend = _Metadata()
    RecoveryStateManager.save(backend, ACTION, PARENT, RecoveryState())
    (key,) = backend.store
    stored = json.loads(backend.store[key])
    stored["phase"] = UNKNOWN
    backend.store[key] = json.dumps(stored)

    with pytest.raises(UnknownRecoveryState) as raised:
        RecoveryStateManager.load(backend, ACTION, PARENT)

    message = _assert_refusal(raised.value)
    assert ACTION in message, f"the refusal must name the action, got: {message}"
    assert PARENT in message, f"the refusal must name the file, got: {message}"


def test_an_entry_with_missing_fields_is_still_skipped():
    """The refusal must not turn ordinary registry leniency into a hard failure."""
    manager = BatchRegistryManager(_registry_with({"batch_id": "b"}), ACTION)

    assert set(manager.get_all_jobs()) == {PARENT}
