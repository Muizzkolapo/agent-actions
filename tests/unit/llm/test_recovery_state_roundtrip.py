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


def test_the_reprompt_counters_still_survive():
    state = RecoveryState(reprompt_attempt=2, reprompt_max_attempts=3, validation_name="schema")
    restored = RecoveryState(**state.to_dict())
    assert restored.reprompt_attempt == 2
    assert restored.reprompt_max_attempts == 3
    assert restored.validation_name == "schema"


def test_the_phase_survives_as_an_enum():
    restored = RecoveryState(**RecoveryState(phase=RecoveryPhase.REPAIR).to_dict())
    assert restored.phase is RecoveryPhase.REPAIR
