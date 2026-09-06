"""Recovery state must survive the round trip that a deferred batch depends on.

Every field is loop state read back on the next pass. A field that serializes to
nothing does not fail loudly — the loop just never advances, which looks like a
provider problem rather than a dropped counter.
"""

import dataclasses

from agent_actions.llm.batch.core.batch_constants import RecoveryPhase
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState


def test_every_field_survives_to_dict():
    """to_dict is what save() persists; a field missing from it is silently lost."""
    declared = {f.name for f in dataclasses.fields(RecoveryState)}
    assert declared - set(RecoveryState().to_dict()) == set()


def test_a_repair_round_counter_survives_the_round_trip():
    state = RecoveryState(
        phase=RecoveryPhase.REPAIR,
        repair_attempt=1,
        repair_max_attempts=2,
    )
    restored = RecoveryState(**state.to_dict())
    assert restored.repair_attempt == 1
    assert restored.repair_max_attempts == 2


def test_the_phase_survives_as_an_enum():
    restored = RecoveryState(**RecoveryState(phase=RecoveryPhase.REPAIR).to_dict())
    assert restored.phase is RecoveryPhase.REPAIR


def test_what_to_dict_produces_is_actually_json():
    """Key presence is not enough — save() writes it with json.dumps.

    to_dict derives from the dataclass fields, so a newly declared field is
    persisted automatically. That is the point, but it also means a field whose
    type json cannot encode reaches disk only as a runtime failure mid-run.
    """
    import json

    state = RecoveryState(
        phase=RecoveryPhase.REPAIR,
        repair_attempt=1,
        repair_max_attempts=2,
        repair_submitted_ids=["r1"],
        repair_judge_budget_remaining=3,
        graduated_results=[{"custom_id": "g1", "content": {"a": 1}, "success": True}],
    )
    json.dumps(state.to_dict())


def test_a_state_file_from_before_the_repair_fields_still_loads():
    """A run started on an older build resumes on this one, not from scratch.

    load() answers a construction failure with None, which restarts the deferred
    loop having lost the graduated pool — so this must not be left to chance.
    """
    old_shape = {
        "phase": "repair",
        "graduated_results": [{"custom_id": "g1", "content": {"a": 1}, "success": True}],
        "evaluation_strategy_name": "validation",
    }
    restored = RecoveryState(**old_shape)
    assert restored.graduated_results[0]["custom_id"] == "g1"
    assert restored.repair_attempt == 0
    assert restored.repair_submitted_ids == []
