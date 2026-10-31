"""Preflight refuses a guard calling an unregistered function or the wrong arity.

Letting function-call syntax through the parser for guards (1383) opened a silent-failure
path: a typo'd or unsupported name, or a wrong argument count, parsed cleanly and raised a
plain `ValueError` only once a record reached it. `GuardFilter` classifies that as a `DATA`
error, which respects `passthrough_on_error` (default true) -- so the guard quietly became a
no-op and every record passed, with no warning. Catching it here stops the run before any
record is read, matching the rest of this preflight.
"""

import pytest

from agent_actions.validation.preflight.guard_validation import validate_guard_conditions


def _errors(configs: dict) -> list[str]:
    return validate_guard_conditions(configs)


def _config(clause: str) -> dict:
    return {
        "a1": {},
        "b": {"dependencies": ["a1"], "guard": {"clause": clause}},
    }


@pytest.mark.parametrize(
    ("clause", "fragments"),
    [
        pytest.param(
            "COUNT(a1.name) > 0", ("'COUNT'", "not a registered function"), id="unregistered"
        ),
        # function_name matches by exact case; Length is not LENGTH
        pytest.param("Length(a1.name) > 0", (), id="mis-cased"),
        pytest.param("TRIM(a1.x, a1.y) > 0", ("'TRIM'", "2 argument"), id="too-many-args"),
        pytest.param("LENGTH()", ("0 argument",), id="zero-args"),
        pytest.param("a1.ok AND COUNT(a1.name) > 0", ("'COUNT'",), id="nested-in-and"),
    ],
)
def test_a_bad_call_is_refused(clause, fragments):
    errors = _errors(_config(clause))

    assert len(errors) == 1, errors
    for fragment in fragments:
        assert fragment in errors[0]


def test_the_message_names_the_available_functions():
    errors = _errors(_config("COUNT(a1.name) > 0"))

    assert "LENGTH" in errors[0] and "UPPER" in errors[0]


def test_a_correct_call_is_silent():
    for clause in [
        "LENGTH(a1.name) > 3",
        'UPPER(a1.name) == "X"',
        'LOWER(a1.name) == "x"',
        'TRIM(a1.name) != ""',
    ]:
        assert _errors(_config(clause)) == [], clause
