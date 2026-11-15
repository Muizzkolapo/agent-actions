"""The CLI context fills only the keys an error leaves unset or None."""

from agent_actions.errors import ConfigurationError
from agent_actions.logging.errors.services.context import ErrorContextService

_CLI = {
    "agent": "agent_workflow/w/agent_config/w.yml",
    "workflow": "cli_workflow",
    "operation": "cli_execution",
    "field": "rows",
    "action_name": None,
    "command": "inspect",
}


def _merged(error_context: dict) -> dict:
    error = ConfigurationError("load failed", context=error_context)
    return ErrorContextService.merge_exception_context(error, dict(_CLI))


def test_every_key_the_error_sets_keeps_its_own_value():
    merged = _merged({"agent": "w", "workflow": "w", "operation": "template_rendering"})

    assert (merged["agent"], merged["workflow"], merged["operation"]) == (
        "w",
        "w",
        "template_rendering",
    )


def test_a_key_the_error_sets_to_none_is_filled_from_the_cli():
    merged = _merged({"agent": "w", "field": None})

    assert merged["field"] == "rows"


def test_a_key_the_error_does_not_set_is_filled_from_the_cli():
    merged = _merged({"agent": "w"})

    assert merged["command"] == "inspect"
    assert merged["workflow"] == "cli_workflow"


def test_a_cli_value_that_is_none_is_not_added():
    merged = _merged({"agent": "w"})

    assert "action_name" not in merged
