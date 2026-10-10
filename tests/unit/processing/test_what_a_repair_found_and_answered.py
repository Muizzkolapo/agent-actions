"""What a repair found of the records it named, and which of those it answered.

`agac retry` reads both once its re-run returns, to tell a record it cleared and never
re-decided. Each is kept per run backend and per action.
"""

from agent_actions.processing.disposition_gate import (
    answered_by_repair,
    found_by_repair,
    note_answered_by_repair,
    positions_named_by_repair,
)

RECORDS = [{"source_guid": "a"}, {"source_guid": "b"}, {"source_guid": "c"}]


class _Run:
    """Only a key here, as a run's backend is."""


def test_the_narrowing_notes_what_it_found_for_its_run_and_action():
    run = _Run()

    positions_named_by_repair(RECORDS, {"a", "c", "z"}, storage_backend=run, action_name="act")

    assert found_by_repair(run, "act") == {"a", "c"}
    assert found_by_repair(run, "another") == frozenset()
    assert found_by_repair(_Run(), "act") == frozenset()


def test_a_narrowing_not_told_its_run_and_action_notes_nothing():
    run = _Run()

    positions_named_by_repair(RECORDS, {"a"})
    positions_named_by_repair(RECORDS, {"a"}, storage_backend=run)

    assert found_by_repair(run, "act") == frozenset()


def test_found_is_not_answered():
    """The file holding it can still raise, and the walk carries on past it."""
    run = _Run()

    positions_named_by_repair(RECORDS, {"a"}, storage_backend=run, action_name="act")

    assert answered_by_repair(run, "act") == frozenset()


def test_answered_is_what_the_repair_named_of_a_finished_files_records():
    run = _Run()

    note_answered_by_repair(RECORDS, {"b", "z"}, storage_backend=run, action_name="act")

    assert answered_by_repair(run, "act") == {"b"}
    assert answered_by_repair(run, "another") == frozenset()


def test_an_ordinary_run_answers_nothing_for_a_repair():
    run = _Run()

    note_answered_by_repair(RECORDS, frozenset(), storage_backend=run, action_name="act")
    note_answered_by_repair({"source_guid": "a"}, {"a"}, storage_backend=run, action_name="act")

    assert answered_by_repair(run, "act") == frozenset()


def test_no_backend_has_found_or_answered_nothing():
    note_answered_by_repair(RECORDS, {"a"}, storage_backend=None, action_name="act")

    assert found_by_repair(None, "act") == frozenset()
    assert answered_by_repair(None, "act") == frozenset()
