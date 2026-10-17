"""A repair notes what it found and answered for the records it cleared, narrowed or not.

A retry resuming a halt in full names no record and narrows nothing, yet it clears the
failures it found at the halted action. Found and answered records were noted only where
a run narrowed, so after the resume every cleared record read as never found: "not in its
input", with `--fresh` as the remedy (1329).
"""

from agent_actions.processing.disposition_gate import (
    answered_by_repair,
    found_by_repair,
    note_answered_by_repair,
    note_cleared_by_repair,
    positions_named_by_repair,
)


class _Backend:
    pass


RECORDS = [{"source_guid": "sg-1"}, {"source_guid": "sg-2"}]


def test_nothing_is_noted_for_a_plain_run():
    backend = _Backend()

    kept = positions_named_by_repair(RECORDS, (), storage_backend=backend, action_name="a")
    note_answered_by_repair(RECORDS, (), storage_backend=backend, action_name="a")

    assert kept is None
    assert found_by_repair(backend, "a") == answered_by_repair(backend, "a") == frozenset()


def test_a_cleared_record_is_noted_without_narrowing():
    backend = _Backend()
    note_cleared_by_repair(backend, {"sg-2"})

    kept = positions_named_by_repair(RECORDS, (), storage_backend=backend, action_name="a")
    note_answered_by_repair(RECORDS, (), storage_backend=backend, action_name="a")

    assert kept is None, "a resume narrows nothing"
    assert found_by_repair(backend, "a") == {"sg-2"}
    assert answered_by_repair(backend, "a") == {"sg-2"}
