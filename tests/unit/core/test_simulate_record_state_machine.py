"""Ensure the narrative simulation stays aligned with framework state semantics."""

from simulate_record_state_machine import run_validated_simulation


def test_simulation_validate_mode_matches_framework() -> None:
    run_validated_simulation()
