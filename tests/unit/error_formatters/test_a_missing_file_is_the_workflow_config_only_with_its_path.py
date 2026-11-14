"""A missing file reads as the workflow config only when the error carries that config's path."""

from agent_actions.errors import FileLoadError
from agent_actions.logging.errors.translator import ErrorTranslator

_CONFIG = "/p/agent_workflow/w/agent_config/w.yml"


def test_the_config_path_the_error_carries_is_the_file_to_create():
    error = FileLoadError("Config file not found", context={"config_path": _CONFIG})

    translated = ErrorTranslator().translate(error, {"agent": "w"})

    assert translated.title == "Agent configuration not found"
    assert translated.fix.splitlines()[0] == f"1. Create {_CONFIG}"


def test_a_missing_file_without_a_config_path_is_not_called_the_workflow_config():
    error = FileLoadError("Seed file not found: data.json")

    translated = ErrorTranslator().translate(error, {"agent": "w"})

    assert translated.title == "File not found"
