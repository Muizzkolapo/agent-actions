"""State naming the retired reprompt mechanism must refuse, not vanish."""

from __future__ import annotations

import json

import pytest

from agent_actions.llm.batch.core.batch_constants import RetiredRecoveryState
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

ACTION = "my_action"
PARENT = "my_action_batch"
LEGACY_CHILD = "my_action_reprompt_1"


class _Metadata:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value


def _legacy_registry_json() -> str:
    parent = BatchJobEntry(
        batch_id="batch-parent",
        status="completed",
        timestamp="2026-09-01T09:00:00Z",
        provider="openai",
        file_name=PARENT,
    )
    child = {
        "batch_id": "batch-reprompt-1",
        "status": "completed",
        "timestamp": "2026-09-01T09:01:00Z",
        "provider": "openai",
        "file_name": LEGACY_CHILD,
        "parent_file_name": PARENT,
        "recovery_type": "reprompt",
        "recovery_attempt": 1,
    }
    return json.dumps({PARENT: parent.to_dict(), LEGACY_CHILD: child})


def test_a_retired_recovery_type_raises_an_actionable_error():
    with pytest.raises(RetiredRecoveryState) as exc:
        BatchJobEntry.from_dict(
            {
                "batch_id": "batch-reprompt-1",
                "status": "completed",
                "timestamp": "2026-09-01T09:01:00Z",
                "provider": "openai",
                "recovery_type": "reprompt",
            }
        )
    message = str(exc.value)
    assert "reprompt" in message
    assert "--fresh" in message, f"the message must say what to do, got: {message}"


def test_a_legacy_reprompt_entry_does_not_silently_disappear_from_the_registry():
    """Dropping it makes the parent look unsubmitted, so the next run pays for it again."""
    backend = _Metadata()
    backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = _legacy_registry_json()
    manager = BatchRegistryManager(backend, ACTION)

    with pytest.raises(RetiredRecoveryState) as exc:
        manager.get_all_jobs()

    # `agac batch` resolves an action by sweeping every action's registry, so a
    # refusal that does not name the offending one fails the whole workflow blind.
    message = str(exc.value)
    assert ACTION in message, f"the refusal must name the action, got: {message}"
    assert LEGACY_CHILD in message, f"the refusal must name the entry, got: {message}"


def test_a_genuinely_malformed_entry_is_still_skipped():
    """The retired-type refusal must not turn ordinary registry leniency into a hard failure."""
    backend = _Metadata()
    good = BatchJobEntry(
        batch_id="batch-parent",
        status="completed",
        timestamp="2026-09-01T09:00:00Z",
        provider="openai",
        file_name=PARENT,
    )
    backend.store[f"{BatchRegistryManager.METADATA_KEY_PREFIX}{ACTION}"] = json.dumps(
        {PARENT: good.to_dict(), "junk": {"batch_id": "b", "recovery_type": "not_a_type"}}
    )
    manager = BatchRegistryManager(backend, ACTION)

    jobs = manager.get_all_jobs()
    assert set(jobs) == {PARENT}


def test_a_retired_recovery_phase_is_refused_the_same_way():
    """The registry entry and the state row are two halves of one deferred run."""
    with pytest.raises(RetiredRecoveryState) as exc:
        RecoveryState(phase="reprompt")
    assert "--fresh" in str(exc.value)


def test_a_live_recovery_phase_still_loads():
    assert RecoveryState(phase="repair").phase is not None
