"""Preflight refuses a guard calling an unregistered function or the wrong arity.

Letting function-call syntax through the parser for guards (1383) opened a silent-failure
path: a typo'd or unsupported name, or a wrong argument count, parsed cleanly and raised a
plain `ValueError` only once a record reached it. `GuardFilter` classifies that as a `DATA`
error, which respects `passthrough_on_error` (default true) -- so the guard quietly became a
no-op and every record passed, with no warning. Catching it here stops the run before any
record is read, matching the rest of this preflight.
"""

from agent_actions.validation.preflight.guard_validation import validate_guard_conditions


def _errors(configs: dict) -> list[str]:
    return validate_guard_conditions(configs)


def _config(clause: str) -> dict:
    return {
        "a1": {},
        "b": {"dependencies": ["a1"], "guard": {"clause": clause}},
    }


def test_an_unregistered_function_name_is_refused():
    errors = _errors(_config("COUNT(a1.name) > 0"))

    assert len(errors) == 1, errors
    assert "'COUNT'" in errors[0] and "not a registered function" in errors[0]


def test_the_message_names_the_available_functions():
    errors = _errors(_config("COUNT(a1.name) > 0"))

    assert "LENGTH" in errors[0] and "UPPER" in errors[0]


def test_a_mis_cased_function_name_is_refused():
    """`function_name` matches by exact case; `Length` is not `LENGTH`."""
    errors = _errors(_config("Length(a1.name) > 0"))

    assert len(errors) == 1, errors


def test_too_many_arguments_is_refused():
    errors = _errors(_config("TRIM(a1.x, a1.y) > 0"))

    assert len(errors) == 1, errors
    assert "'TRIM'" in errors[0] and "2 argument" in errors[0]


def test_zero_arguments_is_refused():
    errors = _errors(_config("LENGTH()"))

    assert len(errors) == 1, errors
    assert "0 argument" in errors[0]


def test_a_correct_call_is_silent():
    for clause in [
        "LENGTH(a1.name) > 3",
        'UPPER(a1.name) == "X"',
        'LOWER(a1.name) == "x"',
        'TRIM(a1.name) != ""',
    ]:
        assert _errors(_config(clause)) == [], clause


def test_an_unregistered_function_nested_in_and_is_still_seen():
    errors = _errors(_config("a1.ok AND COUNT(a1.name) > 0"))

    assert len(errors) == 1, errors
    assert "'COUNT'" in errors[0]
