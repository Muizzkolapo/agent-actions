"""An error that carries a hint prints it as the Fix line, whichever formatter renders it (1295).

The formatters each wrote a fixed Fix line of their own and none read `context['hint']`,
so a refusal's remedy was shown nowhere.
"""

import pytest

from agent_actions.errors import PreFlightValidationError, VendorConfigError
from agent_actions.logging.errors import format_user_error

GENERIC = "Check your configuration and try again"


def _fix_line(error: Exception) -> str:
    (fix,) = [line.strip() for line in format_user_error(error).splitlines() if "Fix:" in line]
    return fix


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            PreFlightValidationError("late: reads 'final'", hint="add it to dependencies"),
            id="generic",
        ),
        pytest.param(
            PreFlightValidationError("yaml thing is invalid", hint="add it to dependencies"),
            id="configuration-formatter",
        ),
        pytest.param(
            VendorConfigError("bad vendor", vendor="x", missing_fields=["api_key"]),
            id="vendor-config-error",
        ),
    ],
)
def test_the_fix_line_is_the_errors_hint(error):
    hint = error.context["hint"]

    assert _fix_line(error) == f"Fix: {hint}"


def test_an_error_with_no_hint_keeps_its_formatters_fix():
    fix = _fix_line(PreFlightValidationError("late: reads 'final'"))

    assert GENERIC in fix


def test_a_blank_hint_does_not_replace_the_fix():
    fix = _fix_line(PreFlightValidationError("late: reads 'final'", hint="  "))

    assert GENERIC in fix


def test_the_title_does_not_repeat_the_cli_error_prefix():
    shown = format_user_error(PreFlightValidationError("late: reads 'final'"))

    assert not shown.startswith("Error:")
